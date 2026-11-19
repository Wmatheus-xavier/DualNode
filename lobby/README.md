# DualNode: servidor de lobby (TCP)

Parte D do trabalho final de **CIC0124 Redes de Computadores** (UnB, 2026.2).

O DualNode é um jogo multiplayer em rede para 3 ou 4 jogadores: cada um controla uma moto que deixa rastro, e quem bate em parede, rastro ou outra moto é eliminado. A partida roda **peer-to-peer em UDP**, com um dos jogadores (o host) como árbitro. Antes dela, os jogadores precisam se encontrar, e é isso que o **lobby** faz.

Este documento cobre só o lobby. A especificação completa do protocolo está no [README principal](../README.md).

| Arquivo | O que é |
|---|---|
| `lobby/server.py` | Servidor de lobby: registro, salas, início da partida, PING e erros do protocolo |
| `tests/test_lobby.py` | 17 testes automáticos do lobby |
| `testes_manuais/demo_lobby.py` | Roda os cenários 7 (lado TCP) e 9 contra um lobby ligado e mostra cada mensagem |

---

## Sumário

1. [O que o lobby faz](#1-o-que-o-lobby-faz)
2. [Como executar](#2-como-executar)
3. [Parametrização](#3-parametrização)
4. [Protocolo tratado](#4-protocolo-tratado)
5. [Como o servidor funciona por dentro](#5-como-o-servidor-funciona-por-dentro)
6. [Decisões de projeto](#6-decisões-de-projeto)
7. [Testes](#7-testes)
8. [Perguntas da banca](#8-perguntas-da-banca)
9. [Limitações conhecidas](#9-limitações-conhecidas)

---

## 1. O que o lobby faz

O lobby **só faz descoberta**. Nenhuma mensagem do jogo passa por ele.

```
  Jogador A ──┐                       ┌── REGISTER, CREATE_MATCH / JOIN_MATCH
  Jogador B ──┼── TCP ──► LOBBY ──────┤
  Jogador C ──┘                       └── START_MATCH ──► MATCH_START para todos
                                                         (IP e porta UDP de cada um)

  Depois do MATCH_START:   A (host) ◄── UDP ──► B, C      (o lobby pode até cair)
```

1. Cada jogador se **registra** com nome e porta UDP.
2. Um deles **cria uma sala** (vira o host, slot 0) e os outros **entram**.
3. O criador **inicia**: o lobby manda a todos o `MATCH_START` com o endereço UDP de cada jogador.
4. A partida acontece direto entre os jogadores, em UDP.

---

## 2. Como executar

Requisito: Python 3.10 ou superior. Só usa a biblioteca padrão. Rode sempre **da raiz do projeto**, não de dentro de `lobby/`. No Linux use `python3`; no Windows, `python`.

```bash
# com o arquivo de configuração
python3 -m lobby.server --config config.json

# ou só pela linha de comando
python3 -m lobby.server --port 5000
python3 -m lobby.server --host 192.168.1.9 --port 5000 --log-level DEBUG
```

Ao subir, o lobby mostra onde está escutando e o IP da máquina na rede. **Esse é o IP que os outros jogadores usam em `--lobby-host`.**

```
2026-11-15 21:16:05,370 INFO lobby escutando em 0.0.0.0:5000 (IP na rede: 192.168.1.9)
```

O log também vai para `logs/lobby.log`. Para parar, aperte `Ctrl+C`.

**Firewall:** libere a porta TCP do lobby (no Windows, aceite o aviso em *rede privada*). Redes que isolam os clientes entre si, como o Wi-Fi do campus, impedem a conexão; nesse caso use um roteador próprio ou o hotspot de um celular.

### Demonstração dos cenários

Com o lobby ligado em outro terminal:
```bash
python3 -m testes_manuais.demo_lobby --port 5000
```

### Teste manual sem o jogo

Linux:
```bash
nc 127.0.0.1 5000
{"v":1,"t":"REGISTER","name":"Ana","udp_port":6001}
{"v":1,"t":"LIST_MATCHES"}
```

Windows (PowerShell):
```powershell
@'
import socket, time
s = socket.create_connection(("127.0.0.1", 5000))
s.sendall(b'{"v":1,"t":"REGISTER","name":"Ana","udp_port":6001}\n{"v":1,"t":"DANCAR"}\n')
time.sleep(0.5)
print(s.recv(4096).decode())
'@ | python -
```

Resposta esperada: um `REGISTER_OK` e um `ERROR UNKNOWN_TYPE`, as duas mensagens no mesmo envio.

---

## 3. Parametrização

Nada de endereço, porta ou tempo do protocolo fica fixo no código. A ordem de prioridade é **linha de comando > `config.json` > valores padrão** (`common/config.py`, parte E).

### 3.1 O que vem da configuração

| Parâmetro | Opção de linha de comando | Padrão | O que controla no lobby |
|---|---|---|---|
| `lobby.port` | `--port` / `--lobby-port` | `5000` | Porta TCP em que o lobby escuta |
| *(endereço de escuta)* | `--host` / `--lobby-host` | `0.0.0.0` | Interface de escuta. Sem `--host`, escuta em todas |
| `lobby.game.width` | | `40` | Largura da arena, enviada no `MATCH_START` |
| `lobby.game.height` | | `20` | Altura da arena, enviada no `MATCH_START` |
| `lobby.game.tick_ms` | | `100` | Duração do ciclo do jogo, enviada no `MATCH_START` |
| `timeouts.lobby_ping_ms` | | `5000` | Intervalo entre os `PING` |
| `timeouts.lobby_dead_ms` | | `15000` | Tempo sem nenhum dado até remover o jogador (precisa ser maior que `lobby_ping_ms`) |
| `debug.log_level` | `--log-level` | `INFO` | Nível do log (`DEBUG`, `INFO`, `WARNING`) |
| — | `--config` | `config.json` | Caminho do arquivo de configuração |

Arena e velocidade são definidas **pelo lobby** e entregues a todos no `MATCH_START`. Assim, todos os jogadores usam os mesmos valores, mesmo que o `config.json` de cada um seja diferente.

**O lobby não usa `lobby.host`.** Esse campo diz aos jogadores onde encontrar o lobby. Para o servidor, o endereço de escuta vem de `--host`; se ele usasse `lobby.host` (padrão `127.0.0.1`), ninguém de outra máquina conseguiria conectar. As chaves `peer.*` e os outros `timeouts.*` são dos jogadores.

Exemplo de `config.json` para o lobby:
```json
{
  "lobby": { "port": 5000, "game": { "width": 40, "height": 20, "tick_ms": 100 } },
  "timeouts": { "lobby_ping_ms": 5000, "lobby_dead_ms": 15000 },
  "debug": { "log_level": "INFO" }
}
```

### 3.2 O que é fixo por ser regra do protocolo

Estes valores vêm da especificação ([README principal](../README.md), seções 9 e 12). Torná-los configuráveis quebraria a compatibilidade entre implementações.

| Regra | Valor | Onde está |
|---|---|---|
| Nome do jogador | 1 a 16 caracteres `[A-Za-z0-9_-]` | `NOME_OK` |
| Porta UDP | 1024 a 65535 | `_on_register` |
| Jogadores por sala | 3 ou 4 | `_on_create_match` |
| Mínimo para iniciar | 3 | `_on_start_match` |
| Tamanho máximo de linha | 4096 bytes | `protocol.MAX_LINE_SIZE` |
| `BAD_FORMAT` seguidos até fechar | 3 | `MAX_FORMATO_SEGUIDOS` |
| Versão do protocolo | `"v": 1` | `protocol.PROTOCOL_VERSION` |

### 3.3 Limites internos da implementação

Não fazem parte do protocolo e não mudam o comportamento visto pelos jogadores.

| Constante | Valor | Por quê |
|---|---|---|
| `SEND_TIMEOUT_S` | 2 s | Um cliente que parou de ler não pode travar o envio para todo mundo. Se o envio não terminar nesse tempo, o jogador é removido |
| `MAX_NOME_SALA` | 24 caracteres | O protocolo não limita o nome da sala; o limite é para caber na tela do lobby |
| Espera do `select` | 0,2 s | De quanto em quanto tempo o laço acorda para mandar `PING` e verificar quem sumiu |

---

## 4. Protocolo tratado

Cada mensagem é um objeto JSON em UTF-8 terminado por `\n`, com `"v": 1` e `"t"` (tipo). A especificação completa está em [README principal](../README.md), seção 9.

### 4.1 Mensagens

| Recebe | Responde | Efeito |
|---|---|---|
| `REGISTER` | `REGISTER_OK` | Registra nome e endereço UDP |
| `LIST_MATCHES` | `MATCH_LIST` | Lista as salas que ainda não começaram |
| `CREATE_MATCH` | `MATCH_CREATED` | Cria a sala; o criador fica no slot 0 (host) |
| `JOIN_MATCH` | `JOIN_OK` (com todos da sala) | Entra no menor slot livre; os outros recebem `PLAYER_JOINED` |
| `LEAVE_MATCH` | *(sem resposta)* | Sai da sala; os outros recebem `PLAYER_LEFT`. Se quem saiu foi o criador: `MATCH_CANCELLED` |
| `START_MATCH` | `MATCH_START` para todos | Só o criador, com pelo menos 3 jogadores |
| `MATCH_END` | *(sem resposta)* | O host informa o fim; ele volta ao menu |
| `PING` | `PONG` | Em qualquer estado |
| `PONG` | *(nada)* | Só prova que o jogador está vivo |

Exemplo de `MATCH_START`:
```json
{"v":1,"t":"MATCH_START","match_id":"m1","host_slot":0,
 "config":{"width":40,"height":20,"tick_ms":100},
 "players":[{"slot":0,"name":"Ana","host":"192.168.1.9","port":6001},
            {"slot":1,"name":"Bob","host":"192.168.1.15","port":6002},
            {"slot":2,"name":"Cid","host":"192.168.1.20","port":6003}]}
```

### 4.2 Máquina de estados (por conexão)

```
            accept()
               │
               ▼
          CONNECTED ──── REGISTER ok ───► REGISTERED ◄───────────────────────┐
                                           │      ▲                          │
                        CREATE / JOIN ok   │      │  LEAVE_MATCH             │ MATCH_END, ou
                                           ▼      │  MATCH_CANCELLED         │ LIST/CREATE/JOIN
                                          IN_ROOM ┘                          │ (voltou ao menu)
                                           │                                 │
                               MATCH_START │                                 │
                                           ▼                                 │
                                          IN_GAME ──────────────────────────┘
```

| Estado | Aceita | Qualquer outra mensagem |
|---|---|---|
| `CONNECTED` | `REGISTER`, `PONG` | `ERROR BAD_STATE` |
| `REGISTERED` | `LIST_MATCHES`, `CREATE_MATCH`, `JOIN_MATCH`, `PONG` | `ERROR BAD_STATE` |
| `IN_ROOM` | `LEAVE_MATCH`, `START_MATCH`, `LIST_MATCHES`, `PONG` | `ERROR BAD_STATE` |
| `IN_GAME` | `MATCH_END`; `LIST_MATCHES`/`CREATE_MATCH`/`JOIN_MATCH` levam de volta a `REGISTERED` | ignorada |

Uma mensagem no estado errado **não muda o estado**.

### 4.3 Erros

| Código | Quando |
|---|---|
| `BAD_FORMAT` | A linha não é JSON, não é objeto ou não tem `v`/`t` válidos. Depois de 3 seguidos, a conexão é fechada |
| `UNKNOWN_TYPE` | O `t` não existe no protocolo |
| `INVALID_PARAM` | Campo faltando, tipo errado ou valor fora da faixa (nome, porta, `max_players`, `udp_host` que não é IPv4 numérico, porta UDP repetida na sala) |
| `BAD_STATE` | Mensagem válida no estado errado |
| `NAME_TAKEN` | O nome já está em uso |
| `MATCH_NOT_FOUND` | O `match_id` não existe |
| `MATCH_FULL` | A sala está cheia |
| `MATCH_STARTED` | A partida já começou |
| `NOT_CREATOR` | Alguém que não é o criador tentou iniciar |
| `NOT_ENOUGH_PLAYERS` | Tentou iniciar com menos de 3 jogadores |

Sem resposta de erro, a conexão é fechada quando chega uma linha maior que 4096 bytes, quando o jogador fica mudo por `lobby_dead_ms` (em `CONNECTED` ou `IN_ROOM`) e quando um envio não termina em 2 s.

**Nenhuma mensagem derruba o servidor:** qualquer exceção ao tratar uma mensagem é registrada no log e respondida com `ERROR`.

---

## 5. Como o servidor funciona por dentro

### Um único thread com `selectors`

O servidor tem um laço só. O `selectors` informa quais sockets têm dados para ler: o socket de escuta (nova conexão → `accept`) ou o de algum jogador (`recv`). A cada volta, o laço também manda `PING` e remove quem sumiu. Sem threads, não há condição de corrida entre jogadores mexendo na mesma sala.

### Enquadramento: o TCP é um fluxo, não mensagens

Um `recv()` pode trazer **meia mensagem, uma mensagem ou várias**. Por isso cada conexão tem o seu próprio buffer:

```python
j.buf += dados
while b"\n" in j.buf:
    linha, j.buf = j.buf.split(b"\n", 1)   # uma mensagem completa
    processar(linha)
# o que sobrou (sem "\n") espera o próximo recv
```

Se o buffer passar de 4096 bytes sem nenhum `\n`, a conexão é fechada. Sem esse limite, um cliente poderia mandar bytes sem parar até acabar a memória do servidor.

O `LineBuffer` do `protocol.py` faz a mesma coisa, mas devolve só `None` para uma linha inválida. O lobby precisa saber o **motivo** (`BAD_FORMAT`, `UNKNOWN_TYPE` ou `INVALID_PARAM`), então separa as linhas ele mesmo e usa `protocol.classify_line`.

### Estruturas

| Classe | Guarda |
|---|---|
| `Jogador` | Socket, buffer, estado, nome, endereço UDP, sala, slot, último instante em que chegou dado |
| `Sala` | `match_id`, nome, criador, máximo de jogadores, `slot → Jogador` |
| `LobbyServer` | Jogadores por socket, salas abertas, salas já iniciadas, laço principal |

Cada tipo de mensagem tem um método `_on_<tipo>` (`_on_register`, `_on_join_match`, ...). Antes de chamar o método, `_processar_linha` valida o formato e confere se a mensagem é aceita no estado atual.

---

## 6. Decisões de projeto

**1. Fim da partida para quem não é host.** O `main.py` mantém a conexão TCP aberta durante o jogo, e só o host manda `MATCH_END`. Os outros jogadores ficariam presos em `IN_GAME`. Por isso, se alguém em `IN_GAME` manda `LIST_MATCHES`, `CREATE_MATCH` ou `JOIN_MATCH`, o lobby entende que a partida dele acabou e volta o estado para `REGISTERED`. Isso também resolve o caso em que o host cai e o `MATCH_END` nunca chega.

**2. Quem é removido por silêncio.** O lobby manda `PING` para todos, menos para quem está em partida. Mas só remove por falta de resposta quem está em `CONNECTED` ou `IN_ROOM`:
- Em `IN_GAME`, o jogador não lê o TCP: ele está jogando.
- Em `REGISTERED`, o jogador está no menu, que espera o teclado e não responde `PING`. Quem demorasse 15 s para digitar o nome da sala seria derrubado. Aqui, quem detecta a saída é o fechamento da conexão.

**3. IP numérico no `MATCH_START`.** O host valida a origem dos pacotes UDP pelo endereço do `MATCH_START`, então `localhost` ou `0.0.0.0` quebrariam o jogo. As regras são:
- Se o jogador não informa `udp_host`, o lobby usa o IP de origem da conexão TCP.
- Se esse IP é `127.x.x.x` (jogador na mesma máquina do lobby), o lobby troca pelo IP da máquina na rede, que funciona para todos.
- `udp_host` que não é IPv4 numérico, ou que é `0.0.0.0`, recebe `INVALID_PARAM`.

**4. Porta UDP repetida.** Dois jogadores na mesma máquina com a mesma `--udp-port` não podem estar na mesma sala, porque o host não conseguiria distingui-los. O `JOIN_MATCH` é recusado com uma mensagem explicando o problema.

**5. Slots estáveis.** O slot vira o `pid` do jogador na partida. Quem entra recebe o **menor slot livre**, e ninguém muda de slot quando outro sai. Pode haver buraco (slots 0, 2, 3), e o host trata isso.

---

## 7. Testes

```bash
python3 -m unittest discover -s tests -t .      # todos os testes do projeto
python3 -m unittest tests.test_lobby -v         # só os do lobby
```

Os testes sobem um lobby de verdade numa porta livre (em outro thread) e conversam com ele por socket, com tempos curtos (`PING` a cada 100 ms, remoção em 600 ms).

| Área | Testes |
|---|---|
| Enquadramento | Duas mensagens num envio; mensagem partida em dois envios; linha acima de 4096 bytes |
| Erros de protocolo | `BAD_FORMAT` 3 vezes fecha; `UNKNOWN_TYPE`; `INVALID_PARAM`; `BAD_STATE` sem mudar o estado |
| Registro | Nome inválido ou longo, porta fora da faixa, `localhost`, `0.0.0.0`, `NAME_TAKEN` |
| Salas | Criar, listar, entrar, avisos de `PLAYER_JOINED`; `MATCH_NOT_FOUND`, `MATCH_FULL`, porta repetida; sair; criador sai e cancela; desconexão avisa a sala |
| Início | `NOT_CREATOR`, `NOT_ENOUGH_PLAYERS`, `MATCH_START` igual para todos, com IPs numéricos e a configuração da arena; sala iniciada some da lista e dá `MATCH_STARTED` |
| Pós-partida | Host volta com `MATCH_END`; jogador comum volta com um pedido do menu |
| Vida | Quem não responde `PING` na sala é removido e a sala é avisada; conexão muda sem `REGISTER` é fechada; quem está em partida não recebe `PING` |

---

## 8. Perguntas da banca

**Por que TCP no lobby?** O tráfego é pouco e esporádico, mas precisa chegar e na ordem certa: não faz sentido perder um `JOIN_MATCH` ou receber o `MATCH_START` antes do `PLAYER_JOINED`. Além disso, o fechamento da conexão já indica que o jogador saiu. O custo extra do TCP (handshake, cabeçalho maior) é irrelevante nessa frequência.

**Como o lobby sabe que um jogador caiu?** De três jeitos:
- O `recv()` devolve `b""`: o outro lado fechou a conexão normalmente (FIN).
- O `recv()` lança exceção: a conexão foi resetada (RST).
- Nenhum dado chega por `lobby_dead_ms`: cobre o caso em que a máquina some sem avisar, como um cabo puxado. Por isso existe o `PING`.

**O que acontece com a partida se o lobby cair?** Nada. Depois do `MATCH_START`, cada jogador já tem o IP e a porta UDP dos outros, e o jogo não usa mais o lobby. Só não dá para criar partidas novas até ele voltar.

**Como lidar com duas mensagens no mesmo `recv`?** O TCP não preserva os limites das mensagens. Cada conexão tem um buffer: junta os bytes que chegam, corta em cada `\n` e guarda a sobra para o próximo `recv`. Os testes `test_duas_mensagens_no_mesmo_recv` e `test_mensagem_partida_em_dois_envios` provam os dois casos.

---

## 9. Limitações conhecidas

- **Só IPv4.**
- **Jogador no menu que some sem fechar a conexão** (máquina desligada da tomada) mantém o nome ocupado até o sistema operacional derrubar o TCP. Os casos comuns (fechar o programa, `Ctrl+C`, `kill`) fecham a conexão e são detectados na hora.
- **O envio usa socket bloqueante com timeout.** Um cliente que parou de ler pode atrasar o servidor em até 2 s antes de ser removido. A alternativa (buffer de saída por conexão e `EVENT_WRITE`) seria mais robusta, mas bem mais complexa para o tamanho do problema.
- **Uma sala iniciada não volta para a lista.** Revanche é uma sala nova.
