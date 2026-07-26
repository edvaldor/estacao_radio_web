# Estação Rádio Web 2.0.2

Receptor portátil para Raspberry Pi, RTL-SDR e tela touch de 3,2″. A versão 2
foi desenhada para 480 × 320 e continua utilizável em 320 × 240.

## O que funciona

- Recepção real em **WFM, NFM e AM** por `rtl_fm`.
- Som na saída ALSA do Raspberry Pi.
- Medidor em tempo real calculado no áudio PCM recebido.
- Nome das emissoras FM por catálogo local editável.
- Banda, modo e passo escolhidos automaticamente ao digitar a frequência.
- Scanner em FM, aeronáutica, radioamador VHF/UHF e PX/CB.
- Sintonia manual, teclado touch, controle de volume e modo noturno.
- Serviço automático e modo quiosque opcional.
- Instalador e atualizador geral.

O projeto é somente receptor; não transmite.

## Instalação nova

No Raspberry Pi, digite uma linha de cada vez:

```bash
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/edvaldor/estacao_radio_web.git
cd estacao_radio_web
sudo bash install.sh
sudo reboot
```

Depois do reinício, descubra o IP:

```bash
hostname -I
```

Abra no navegador:

```text
http://IP_DO_RASPBERRY:5000
```

Exemplo: `http://192.168.1.82:5000`.

## Atualizar uma instalação existente

```bash
cd ~/estacao_radio_web
sudo bash scripts/update.sh
```

O atualizador executa `git pull`, reinstala dependências necessárias e reinicia
o serviço. Se a pasta não tiver sido baixada com `git clone`, renomeie a pasta
antiga e faça a instalação nova.

## Abrir automaticamente na tela de 3,2″

```bash
cd ~/estacao_radio_web
sudo bash scripts/install-kiosk.sh
sudo reboot
```

O instalador desativa o Raspberry Pi Desktop/LightDM porque o quiosque inicia
seu próprio servidor gráfico. Isso evita a tela parada em “Welcome to the
Raspberry Pi Desktop”.

Em telas Waveshare conectadas por SPI, o instalador seleciona automaticamente
`/dev/fb1` e instala o driver Xorg `fbdev`. Sem essa configuração, o Xorg tenta
usar `/dev/dri/card0` e termina com a mensagem `no screens found`.

## Como usar o scanner

1. Toque em **Scanner**.
2. Escolha qualquer uma das cinco bandas.
3. Deixe a sensibilidade em **8 dB** para começar.
4. Toque em **Varrer** e aguarde alguns segundos.
5. O receptor sintoniza o pico mais forte.
6. Use **Anterior** e **Próximo** para percorrer os sinais encontrados.

Durante a medição o áudio para: existe apenas um sintonizador e o `rtl_power`
precisa usá-lo temporariamente. Ao terminar, o áudio volta automaticamente.
Se nenhum sinal for encontrado, reduza a sensibilidade para 5 ou 6 dB. Se
aparecer muito ruído, aumente para 10 ou 12 dB.

## Medidor de sinal

O medidor não é mais uma animação aleatória quando há RTL-SDR. O programa mede
o RMS do áudio que sai do `rtl_fm`, mostra o nível em **dBFS** e movimenta a
escala relativa. Isso serve para comparar sintonia e antenas, mas não é um
medidor de potência calibrado em dBm.

## Nomes das emissoras FM

O nome vem de:

```text
config/stations.json
```

O arquivo já contém emissoras de Cianorte. Para acrescentar outra, copie um
bloco, altere frequência, nome e cidade, salve e atualize a página. Exemplo:

```json
{
  "frequency_mhz": 99.3,
  "name": "Nome da rádio",
  "city": "Cidade - UF"
}
```

Essa identificação funciona offline. RDS verdadeiro não está incluído nesta
versão: a cadeia de áudio do `rtl_fm` usada para ouvir WFM não preserva de modo
adequado a subportadora RDS de 57 kHz. Uma futura versão poderá usar um
decodificador SDR separado.

## Som: saída correta

O instalador procura a placa `Headphones` e, quando encontra, grava:

```text
RADIO_AUDIO_DEVICE=plughw:CARD=Headphones,DEV=0
RADIO_AUDIO_CARD=1
RADIO_AUDIO_MIXER=PCM
```

Para verificar:

```bash
cat /etc/default/estacao-radio-web
aplay -l
```

Depois de alterar esse arquivo:

```bash
sudo systemctl restart estacao-radio-web
```

## Diagnóstico

Testar o dongle:

```bash
rtl_test -t
```

Confirmar que o scanner foi instalado:

```bash
which rtl_power
```

Estado do serviço:

```bash
sudo systemctl status estacao-radio-web
```

Últimas mensagens:

```bash
journalctl -u estacao-radio-web -n 100 --no-pager
```

Reiniciar:

```bash
sudo systemctl restart estacao-radio-web
```

## Limitações e segurança

- `rtl_fm` recebe AM, NFM e WFM; USB e LSB não fazem parte desta versão.
- O scanner encontra energia no espectro, não garante que todo pico contenha
  voz.
- Em bandas de uso intermitente, faça várias varreduras.
- Use somente para recepção e respeite a legislação e a privacidade das
  comunicações.
