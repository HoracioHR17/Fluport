# Despliegue de Fluport con Cloudflare Tunnel y dominio .tech

Fluport corre en la laptop (uvicorn + PostgreSQL local) y Cloudflare Tunnel la publica en `https://<tu-dominio>.tech`
sin abrir puertos ni configurar el router. El bot de Telegram sigue en modo `polling`: no necesita URL pública.

```
Teléfono / jurado ──HTTPS──► Cloudflare (DNS + TLS) ──túnel saliente──► cloudflared (laptop) ──► uvicorn 127.0.0.1:8000
```

## 0. Antes de empezar (hazlo primero: el DNS tarda en propagarse)

1. Crea una cuenta gratuita en Cloudflare → **Add a domain** → escribe `<tu-dominio>.tech` → plan **Free**.
2. Cloudflare muestra **dos nameservers** (por ejemplo `xxx.ns.cloudflare.com`).
3. En el panel de get.tech (Manage Orders → tu dominio → **Name Servers**) reemplaza los nameservers por los dos de Cloudflare.
4. Espera a que Cloudflare marque el dominio como **Active** (de minutos a unas horas). Mientras tanto usa el plan B (paso 7).

## 1. Instalar cloudflared (Pop!_OS / Ubuntu)

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
cloudflared --version
```

## 2. Crear el túnel

```bash
cloudflared tunnel login                 # abre el navegador: elige <tu-dominio>.tech
cloudflared tunnel create fluport        # anota el ID; crea ~/.cloudflared/<ID>.json
cloudflared tunnel route dns fluport <tu-dominio>.tech
cloudflared tunnel route dns fluport www.<tu-dominio>.tech
```

## 3. Configurar `~/.cloudflared/config.yml`

```yaml
tunnel: fluport
credentials-file: /home/horaciohr/.cloudflared/<ID>.json
ingress:
  - hostname: <tu-dominio>.tech
    service: http://localhost:8000
  - hostname: www.<tu-dominio>.tech
    service: http://localhost:8000
  - service: http_status:404
```

```bash
cloudflared tunnel ingress validate
```

El WebSocket del tablero (`/ws/sim`) pasa por el túnel sin configuración extra: la página usa `wss://` cuando se abre por HTTPS.

## 4. Arrancar (tres terminales)

| Terminal | Comando |
|---|---|
| T1 · Fluport | `cd backend && source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers` |
| T2 · Túnel | `cloudflared tunnel run fluport` |
| T3 · Pruebas | `curl -s https://<tu-dominio>.tech/api/salud` |

Con `--host 127.0.0.1` la app solo es accesible por el túnel, no desde la red local.

Opcional, para que el túnel arranque solo: `sudo cloudflared --config ~/.cloudflared/config.yml service install`
(copia la configuración a `/etc/cloudflared/`; revisa con `systemctl status cloudflared`).

## 5. Preparar la laptop para la demo

- Desactiva la suspensión automática (Configuración → Energía) y deja el cargador conectado.
- Ten un hotspot del celular como respaldo de internet.
- En `backend/.env`: `FLUPORT_TELEGRAM_MODO=polling` y `FLUPORT_TELEGRAM_SOLO_REGISTRADOS=true`.

## 6. Proteger el panel de demostración y el de agencias (recomendado, gratis)

`/demo/` permite cerrar casetas y acelerar el reloj, y `/agencia/` todavía no pide inicio de sesión. Con
**Cloudflare Zero Trust → Access → Applications → Self-hosted** crea una aplicación para
`<tu-dominio>.tech/demo/*`, otra para `<tu-dominio>.tech/agencia/*` y otra para `<tu-dominio>.tech/api/sim/*`, con una política
**Allow** para los correos del equipo (código de un solo uso por correo). La vista pública y el bot quedan abiertos.

## 7. Plan B: sin dominio o si el DNS no ha propagado

```bash
cloudflared tunnel --url http://localhost:8000
```

Da una URL temporal `https://<algo>.trycloudflare.com` al instante, sin cuenta. Cambia cada vez que se reinicia.

Plan C: misma red Wi-Fi, `uvicorn ... --host 0.0.0.0` y abrir `http://<IP de la laptop>:8000`.

## 8. Lista de verificación desde un celular con datos móviles

- [ ] `https://<tu-dominio>.tech/` abre la vista pública con candado HTTPS.
- [ ] Los tiempos se actualizan solos (WebSocket o sondeo).
- [ ] El botón "Abrir el bot en Telegram" y el QR funcionan.
- [ ] `/agencia/` (tras Access, si lo activaste): alta de transportista, asignación de cita, mensaje en Telegram, SÍ → confirmada.
- [ ] `/demo/`: cerrar una caseta → alerta en la vista pública → aviso en Telegram.
