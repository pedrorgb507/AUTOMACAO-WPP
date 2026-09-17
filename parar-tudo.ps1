# Encerra todos os robos da automacao e libera o que eles seguram.
#
# Existe porque parar isso na mao erra de tres formas: fechar o terminal nao
# mata o Python; matar o Python nao mata o Chrome do robo, que continua
# segurando o perfil e impede o proximo start; e o OpenWA deixa processos do
# npm presos na porta 2785 mesmo depois de o principal morrer.
#
# No fim ele CONFERE, em vez de apenas mandar encerrar: processo que resiste a
# um Stop-Process nao e raro, e um "parei tudo" que nao parou e pior que um
# erro, porque manda a pessoa religar em cima do que ainda esta rodando.

$ErrorActionPreference = 'SilentlyContinue'

function Alvos {
    $lista = @()

    # os vigias em Python (cada um sobe dois processos: o lancador e o real)
    $lista += Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python.EXE'" |
        Where-Object {
            $_.CommandLine -notlike '*debugpy*' -and (
                $_.CommandLine -like '*vigia_whatsapp*' -or
                $_.CommandLine -like '*vigia_email*'    -or
                $_.CommandLine -like '*vigia_cip*'      -or
                $_.CommandLine -like '*vigiar_teams_e_cip*' -or
                $_.CommandLine -like '*teams_web*'      -or
                $_.CommandLine -like '*drive_api*' )
        }

    # o Chrome do robo (o do dia a dia nao usa esse perfil e nao e tocado)
    $lista += Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
        Where-Object { $_.CommandLine -like '*perfil_teams_web*' }

    # o OpenWA: pelo caminho e, sobretudo, por quem esta ocupando as portas -
    # os invisiveis do npm so aparecem por aqui
    $lista += Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
        Where-Object { $_.CommandLine -like '*OpenWA*' }
    foreach ($porta in 2785, 2886) {
        $conexoes = Get-NetTCPConnection -LocalPort $porta -State Listen
        foreach ($c in $conexoes) {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
            if ($p) { $lista += $p }
        }
    }

    $lista | Sort-Object ProcessId -Unique
}

$alvos = Alvos
if ($alvos.Count -eq 0) {
    Write-Host '   Nada estava rodando.'
} else {
    $alvos | Group-Object Name | ForEach-Object {
        Write-Host ('   encerrando ' + $_.Name + ': ' + $_.Count + ' processo(s)')
    }
    $alvos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep -Seconds 3
}

# Conferencia: o que importa nao e ter mandado encerrar, e ter encerrado.
Write-Host ''
$restou = Alvos
$portas = @()
foreach ($porta in 2785, 2886) {
    if (Get-NetTCPConnection -LocalPort $porta -State Listen) { $portas += $porta }
}

if ($restou.Count -eq 0 -and $portas.Count -eq 0) {
    Write-Host '   OK: tudo encerrado, perfil do Chrome livre e portas 2785/2886 liberadas.'
} else {
    if ($restou.Count -gt 0) {
        Write-Host ('   ATENCAO: ' + $restou.Count + ' processo(s) resistiram:')
        $restou | ForEach-Object { Write-Host ('      ' + $_.Name + ' (pid ' + $_.ProcessId + ')') }
    }
    if ($portas.Count -gt 0) {
        Write-Host ('   ATENCAO: ainda ha algo escutando na(s) porta(s): ' + ($portas -join ', '))
    }
    Write-Host '   Rode este arquivo mais uma vez; se insistir, reinicie o computador.'
}
