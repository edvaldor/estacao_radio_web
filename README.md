# Estação Rádio Web

Interface leve para usar um RTL-SDR com Raspberry Pi e tela touch de 3,2 polegadas. O projeto abre uma estação com medidor de sinal, seletor de bandas, modos, sintonia manual por teclado numérico, passo de frequência, volume e modo noturno.

## O que já funciona

- Interface responsiva para 480 × 320 pixels.
- Teclado numérico ao tocar na frequência.
- Presets para FM comercial, aeronáutica, radioamador VHF/UHF e PX/CB.
- Recepção real por `rtl_fm` nos modos AM, NFM e WFM.
- Saída de áudio pelo ALSA (`aplay`).
- Modo de demonstração quando o RTL-SDR não está conectado.
- Serviço automático no Linux.
- Instalador e atualizador geral.
- Modo quiosque opcional para abrir na tela touch ao ligar.

USB e LSB aparecem na interface, mas ainda não são demodulados pelo `rtl_fm`.

## 1. Colocar os arquivos no GitHub

Descompacte o ZIP. Envie **o conteúdo da pasta `estacao_radio_web`** para:

<https://github.com/edvaldor/estacao_radio_web>

Você pode usar o botão **Add file → Upload files** do GitHub.

## 2. Baixar no Raspberry Pi

Digite no terminal, uma linha por vez:

```bash
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/edvaldor/estacao_radio_web.git
cd estacao_radio_web
sudo bash install.sh
sudo reboot
```

O primeiro reinício é importante: o instalador libera o dongle RTL2832U para uso como rádio.

## 3. Abrir a interface

Depois de reiniciar, descubra o endereço do Raspberry:

```bash
hostname -I
```

Em outro computador ou celular da mesma rede, abra:

```text
http://IP_DO_RASPBERRY:5000
```

Exemplo:

```text
http://192.168.1.82:5000
```

## 4. Abrir automaticamente na tela de 3,2″

Dentro da pasta do projeto:

```bash
cd ~/estacao_radio_web
sudo bash scripts/install-kiosk.sh
sudo reboot
```

Esse passo instala o ambiente gráfico mínimo e abre o Chromium em tela cheia.

## Atualizar pelo GitHub

```bash
cd ~/estacao_radio_web
sudo bash scripts/update.sh
```

O atualizador baixa a versão mais recente, atualiza as dependências e reinicia o serviço.

## Testar o RTL-SDR

```bash
rtl_test -t
```

O resultado esperado contém mensagens semelhantes a:

```text
Found 1 device(s)
Using device 0: Generic RTL2832U OEM
Found Rafael Micro R820T tuner
```

## Comandos úteis

Ver o estado do programa:

```bash
sudo systemctl status estacao-radio-web
```

Ver mensagens de erro:

```bash
journalctl -u estacao-radio-web -n 100 --no-pager
```

Reiniciar o programa:

```bash
sudo systemctl restart estacao-radio-web
```

Executar manualmente:

```bash
cd ~/estacao_radio_web
./run.sh
```

## Testar a interface sem Raspberry Pi

Abra `web/index.html` em um navegador. A tela funcionará no modo demonstração, sem áudio real.

## Estrutura

```text
app.py                  servidor web
radio.py                controle do RTL-SDR
web/index.html          interface
web/app.css             desenho responsivo
web/app.js              controles e teclado
install.sh              instalador geral
scripts/update.sh       atualizador
scripts/install-kiosk.sh abertura automática na tela
scripts/uninstall.sh    remove os serviços
```

## Observações

- Use somente para recepção. Este projeto não transmite sinais.
- Respeite a legislação e não divulgue comunicações protegidas ou privadas.
- O medidor usa uma estimativa visual nesta primeira versão; ele ainda não representa RSSI calibrado.
