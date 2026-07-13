# AgentNet — Comunicação TCP/UDP entre agents (#2891)

**Módulo:** crates/simplicio-agents/src/agent_net.rs (237 linhas)
**Testes:** 6/6 | **Release:** v2.3.0

## Componentes

### AgentTcpServer
bind(addr) -> accept() -> Option<(String, TcpStream)>
Servidor TCP que escuta e aceita conexões de agents.

### AgentTcpClient
connect(addr) -> send(msg) -> recv() -> Result<String, String>
Cliente TCP que conecta e troca mensagens.

### AgentUdpPeer
bind(addr) -> send_to(msg, target) -> recv_from() -> Result<(String, String), String>
Peer UDP sem estado para comunicação rápida.

## Uso típico
```rust
let server = AgentTcpServer::bind("127.0.0.1:0").await?;
let mut client = AgentTcpClient::connect(&addr).await?;
client.send("{\"agent\":\"Isa\",\"type\":\"memory_query\"}").await?;
```
