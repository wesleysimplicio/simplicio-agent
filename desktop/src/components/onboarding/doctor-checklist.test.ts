import { describe, expect, it } from 'vitest'

import { mapDoctorToChecklist } from './doctor-checklist'

describe('mapDoctorToChecklist', () => {
  it('returns an empty list for non-object input', () => {
    expect(mapDoctorToChecklist(null)).toEqual([])
    expect(mapDoctorToChecklist(undefined)).toEqual([])
    expect(mapDoctorToChecklist('nope')).toEqual([])
    expect(mapDoctorToChecklist(42)).toEqual([])
    expect(mapDoctorToChecklist(['array'])).toEqual([])
  })

  it('marks every item unknown (or warning for the model) when the payload is empty', () => {
    const items = mapDoctorToChecklist({})

    expect(items).toHaveLength(5)
    expect(items.map(i => i.id)).toEqual(['binary', 'version', 'overall', 'model', 'repoState'])
    expect(items.map(i => i.status)).toEqual(['unknown', 'unknown', 'unknown', 'warning', 'unknown'])
    // Never invents detail text from a missing field.
    for (const item of items) {
      expect(item.detail).not.toContain('undefined')
      expect(item.detail).not.toContain('null')
    }
  })

  it('extracts binary, version, overall status, and local model from a healthy payload', () => {
    const doctor = {
      version: '3.4.0',
      overall_status: 'ok',
      execution: { binary: '/usr/local/bin/simplicio', runtime_home: '/home/.simplicio' },
      policy: { model: 'gemma4:4b-q4_K_M', local: true, offline_first: true },
      health: { checks: [{ name: 'git', status: 'ok', detail: 'git repo clean' }] }
    }

    const items = mapDoctorToChecklist(doctor)

    expect(items.find(i => i.id === 'binary')).toMatchObject({
      status: 'ok',
      detail: '/usr/local/bin/simplicio'
    })
    expect(items.find(i => i.id === 'version')).toMatchObject({ status: 'ok', detail: '3.4.0' })
    expect(items.find(i => i.id === 'overall')).toMatchObject({ status: 'ok', detail: 'ok', fixHint: undefined })
    expect(items.find(i => i.id === 'model')).toMatchObject({
      status: 'ok',
      detail: 'gemma4:4b-q4_K_M (local)'
    })
    expect(items.find(i => i.id === 'repoState')).toMatchObject({ status: 'ok', detail: 'git repo clean' })
  })

  it('labels a remote (non-local) model correctly', () => {
    const items = mapDoctorToChecklist({ policy: { model: 'deepseek/deepseek-v4-flash', local: false } })

    expect(items.find(i => i.id === 'model')).toMatchObject({
      status: 'ok',
      detail: 'deepseek/deepseek-v4-flash (remoto)'
    })
  })

  it('surfaces a warning overall status with a fix hint', () => {
    const overall = mapDoctorToChecklist({ overall_status: 'warning' }).find(i => i.id === 'overall')

    expect(overall?.status).toBe('warning')
    expect(overall?.fixHint).toBeTruthy()
  })

  it('surfaces an error overall status with a repair fix hint', () => {
    const overall = mapDoctorToChecklist({ overall_status: 'error' }).find(i => i.id === 'overall')

    expect(overall?.status).toBe('error')
    expect(overall?.fixHint).toContain('doctor --repair')
  })

  it('treats an unrecognized overall_status value as unknown, never invented', () => {
    const overall = mapDoctorToChecklist({ overall_status: 'quantum-flux' }).find(i => i.id === 'overall')

    expect(overall?.status).toBe('unknown')
    expect(overall?.detail).toBe('quantum-flux')
  })

  it('never crashes on malformed nested fields', () => {
    const doctor = {
      execution: 'not-an-object',
      policy: null,
      health: { checks: 'not-an-array' }
    }

    expect(() => mapDoctorToChecklist(doctor)).not.toThrow()
    expect(mapDoctorToChecklist(doctor)).toHaveLength(5)
  })

  it('falls back to the runtime-home check when git is absent', () => {
    const doctor = { health: { checks: [{ name: 'runtime-home', status: 'warning', detail: 'home missing' }] } }
    const repoState = mapDoctorToChecklist(doctor).find(i => i.id === 'repoState')

    expect(repoState).toMatchObject({ status: 'warning', detail: 'home missing' })
    expect(repoState?.fixHint).toContain('doctor --repair')
  })

  it('prefers the git check over runtime-home when both are present', () => {
    const doctor = {
      health: {
        checks: [
          { name: 'runtime-home', status: 'warning', detail: 'home missing' },
          { name: 'git', status: 'ok', detail: 'git repo clean' }
        ]
      }
    }

    expect(mapDoctorToChecklist(doctor).find(i => i.id === 'repoState')).toMatchObject({
      status: 'ok',
      detail: 'git repo clean'
    })
  })

  it('folds the runtime "info" health status into ok', () => {
    const doctor = { health: { checks: [{ name: 'git', status: 'info', detail: 'informational only' }] } }

    expect(mapDoctorToChecklist(doctor).find(i => i.id === 'repoState')).toMatchObject({ status: 'ok' })
  })
})
