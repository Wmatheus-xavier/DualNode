"""
Simulador de rede ruim para testes: perda, atraso e jitter em um socket UDP.

Embrulha um socket UDP já aberto e se comporta como ele (só o que o Host usa:
recvfrom, sendto e close). A perda vale nos DOIS sentidos, em cada datagrama.

    sock = SimSocket(sock_udp, loss=0.2, delay_ms=80, jitter_ms=40, seed=7)

- loss:      probabilidade (0 a 1) de descartar cada datagrama, ao enviar e ao receber.
- delay_ms:  atraso fixo de cada datagrama, em cada sentido.
- jitter_ms: variação aleatória (+/-) somada ao atraso. Com jitter, datagramas podem
             chegar FORA DE ORDEM, como numa rede de verdade.
- seed:      semente do sorteio; a mesma semente reproduz o mesmo padrão de perdas.

O atraso do envio é "despachado" a cada chamada de recvfrom/sendto, então o código que usa o
socket precisa chamar recvfrom com frequência (o laço do host já faz isso a cada poucos ms).
"""
import heapq
import random
import time


class SimSocket:
    def __init__(self, sock, loss=0.0, delay_ms=0.0, jitter_ms=0.0, seed=None):
        self.sock = sock
        self.loss = float(loss)
        self.delay = float(delay_ms) / 1000
        self.jitter = float(jitter_ms) / 1000
        self.rng = random.Random(seed)
        self._entrada = []       # heap: (instante de entrega, ordem, dados, addr)
        self._saida = []
        self._ordem = 0
        self.stats = {"rx": 0, "rx_perdidos": 0, "tx": 0, "tx_perdidos": 0}

    # -- internos --

    def _instante(self):
        atraso = self.delay
        if self.jitter:
            atraso += self.rng.uniform(-self.jitter, self.jitter)
        return time.monotonic() + max(0.0, atraso)

    def _empurrar(self, fila, dados, addr):
        self._ordem += 1
        heapq.heappush(fila, (self._instante(), self._ordem, dados, addr))

    def _puxar_do_socket(self):
        while True:
            try:
                dados, addr = self.sock.recvfrom(2048)
            except BlockingIOError:
                break
            except ConnectionResetError:
                continue
            self.stats["rx"] += 1
            if self.rng.random() < self.loss:
                self.stats["rx_perdidos"] += 1
                continue
            self._empurrar(self._entrada, dados, addr)

    def _despachar_saida(self):
        agora = time.monotonic()
        while self._saida and self._saida[0][0] <= agora:
            _, _, dados, addr = heapq.heappop(self._saida)
            self.sock.sendto(dados, addr)

    # -- a interface do socket --

    def sendto(self, dados, addr):
        self.stats["tx"] += 1
        if self.rng.random() < self.loss:
            self.stats["tx_perdidos"] += 1
            return len(dados)
        self._empurrar(self._saida, dados, addr)
        self._despachar_saida()
        return len(dados)

    def recvfrom(self, n):
        self._despachar_saida()
        self._puxar_do_socket()
        if self._entrada and self._entrada[0][0] <= time.monotonic():
            _, _, dados, addr = heapq.heappop(self._entrada)
            return dados[:n], addr
        raise BlockingIOError

    def close(self):
        """Datagramas já 'na rede' (atrasados) ainda chegam: espera despachar a fila de saída."""
        limite = time.monotonic() + self.delay + self.jitter + 0.2
        while self._saida and time.monotonic() < limite:
            self._despachar_saida()
            time.sleep(0.002)
        self.sock.close()