Camera360 - Controle de Camera
============================

Este programa nao precisa de Python, MSYS2 ou qualquer outra instalacao
para rodar - tudo ja vem empacotado dentro da pasta de instalacao.

Se a camera nao for detectada (aparece "modo simulacao")
---------------------------------------------------------
No Windows, a camera normalmente aparece associada ao driver MTP padrao,
mas o Camera360 precisa que ela use o driver WinUSB para conseguir se
comunicar com ela (isso e uma exigencia do Windows, nao do Camera360).

Para trocar o driver da sua camera para WinUSB (feito uma unica vez por
computador/camera):

1. Baixe o Zadig (gratuito, oficial) em: https://zadig.akeo.ie/
2. Conecte a camera via USB e ligue ela.
3. Abra o Zadig, va em Options > List All Devices e marque essa opcao.
4. Selecione o modelo da sua camera na lista.
5. Escolha o driver "WinUSB" e clique em "Replace Driver" (ou "Install Driver").
6. Feche o Zadig e abra o Camera360 novamente.

Se mesmo assim a camera nao conectar, verifique:
- Se a bateria da camera nao esta descarregada (algumas cameras bloqueiam
  o live view com bateria fraca).
- Se a camera esta no modo de conexao correto (PTP/PC, nao modo de
  armazenamento em massa).

Onde as fotos e videos sao salvos
----------------------------------
Na pasta "capturas" dentro do diretorio onde o Camera360 foi instalado.
