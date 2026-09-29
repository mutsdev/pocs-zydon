import { useEffect, useRef, useState } from 'react'
import { Atom, Sparkles } from 'lucide-react'

type Cena = 'caos' | 'galton'

interface Props { titulo: string; mensagem?: string | null; desde?: string | null }

function cor(nome: string, reserva: string) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome).trim()
  return v || reserva
}

function rgb(hex: string) {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

const PENDULOS = 240
const G = 9.81

function derivadas(s: number[]) {
  const [a1, a2, w1, w2] = s
  const d = a1 - a2
  const den = 3 - Math.cos(2 * d)
  const dw1 = (-3 * G * Math.sin(a1) - G * Math.sin(a1 - 2 * a2) - 2 * Math.sin(d) * (w2 * w2 + w1 * w1 * Math.cos(d))) / den
  const dw2 = (2 * Math.sin(d) * (2 * w1 * w1 + 2 * G * Math.cos(a1) + w2 * w2 * Math.cos(d))) / den
  return [w1, w2, dw1, dw2]
}

function passoRK4(s: number[], h: number) {
  const k1 = derivadas(s)
  const k2 = derivadas(s.map((v, i) => v + (h / 2) * k1[i]))
  const k3 = derivadas(s.map((v, i) => v + (h / 2) * k2[i]))
  const k4 = derivadas(s.map((v, i) => v + h * k3[i]))
  return s.map((v, i) => v + (h / 6) * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]))
}

function cenaCaos(ctx: CanvasRenderingContext2D, largura: number, altura: number) {
  let estados = Array.from({ length: PENDULOS }, (_, i) => [Math.PI * 0.92 + i * 1e-9, Math.PI * 0.92, 0, 0])
  const fundo = rgb(cor('--color-surface', '#19181a'))
  let t = 0
  return () => {
    for (let k = 0; k < 4; k++) estados = estados.map((s) => passoRK4(s, 0.004))
    t += 0.016
    ctx.fillStyle = `rgba(${fundo[0]},${fundo[1]},${fundo[2]},0.16)`
    ctx.fillRect(0, 0, largura, altura)
    const cx = largura / 2
    const cy = altura * 0.36
    const l = Math.min(largura, altura) * 0.2
    ctx.lineWidth = 1.1
    ctx.globalCompositeOperation = 'lighter'
    estados.forEach((s, i) => {
      const x1 = cx + l * Math.sin(s[0])
      const y1 = cy + l * Math.cos(s[0])
      const x2 = x1 + l * Math.sin(s[1])
      const y2 = y1 + l * Math.cos(s[1])
      const matiz = 68 + (i / PENDULOS) * 140
      ctx.strokeStyle = `hsla(${matiz}, 95%, 58%, 0.35)`
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.lineTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.stroke()
      ctx.fillStyle = `hsla(${matiz}, 100%, 65%, 0.9)`
      ctx.fillRect(x2 - 1.2, y2 - 1.2, 2.4, 2.4)
    })
    ctx.globalCompositeOperation = 'source-over'
    const [a1, a2] = estados.reduce((acc, s) => [Math.max(acc[0], s[0]), Math.min(acc[1], s[0])], [-Infinity, Infinity])
    return { legenda: `${PENDULOS} pêndulos duplos que começaram a 0,000000001 rad um do outro`, extra: `divergência: ${((a1 - a2) * 57.3).toFixed(t < 3 ? 6 : 1)}°` }
  }
}

function cenaGalton(ctx: CanvasRenderingContext2D, largura: number, altura: number) {
  const primaria = cor('--color-primary', '#cdeb00')
  const texto = rgb(cor('--color-text-secondary', '#a9ad9b'))
  const fundo = cor('--color-surface', '#19181a')
  const linhas = 13
  const espaco = Math.min(largura / (linhas + 5), altura / (linhas + 9))
  const topo = espaco * 2.2
  const pinos: { x: number; y: number }[] = []
  for (let r = 0; r < linhas; r++) for (let c = 0; c <= r; c++) pinos.push({ x: largura / 2 + (c - r / 2) * espaco, y: topo + r * espaco * 0.9 })
  const raioPino = Math.max(1.6, espaco * 0.08)
  const raioBola = Math.max(2, espaco * 0.16)
  const baseY = altura - 6
  const inicioCaixas = topo + linhas * espaco * 0.9 + espaco * 0.4
  const caixas = new Array(linhas + 1).fill(0)
  let bolas: { x: number; y: number; vx: number; vy: number }[] = []
  let total = 0
  let quadro = 0
  const gravidade = espaco * 0.018
  return () => {
    quadro++
    if (quadro % 3 === 0 && bolas.length < 260) bolas.push({ x: largura / 2 + (Math.random() - 0.5) * 0.6, y: topo - espaco, vx: 0, vy: 0 })
    ctx.fillStyle = fundo
    ctx.fillRect(0, 0, largura, altura)
    const maximo = Math.max(1, ...caixas)
    const alturaUtil = baseY - inicioCaixas
    caixas.forEach((n, i) => {
      const x = largura / 2 + (i - linhas / 2) * espaco
      const h = (n / maximo) * alturaUtil
      const grad = ctx.createLinearGradient(0, baseY - h, 0, baseY)
      grad.addColorStop(0, primaria)
      grad.addColorStop(1, `rgba(${texto[0]},${texto[1]},${texto[2]},0.15)`)
      ctx.fillStyle = grad
      ctx.fillRect(x - espaco * 0.42, baseY - h, espaco * 0.84, h)
    })
    const media = linhas / 2
    const desvio = Math.sqrt(linhas / 4)
    ctx.strokeStyle = `rgba(${texto[0]},${texto[1]},${texto[2]},0.8)`
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    for (let k = 0; k <= 200; k++) {
      const i = (k / 200) * linhas
      const densidade = Math.exp(-((i - media) ** 2) / (2 * desvio * desvio))
      const x = largura / 2 + (i - linhas / 2) * espaco
      const y = baseY - densidade * alturaUtil
      if (k === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = `rgba(${texto[0]},${texto[1]},${texto[2]},0.9)`
    pinos.forEach((p) => { ctx.beginPath(); ctx.arc(p.x, p.y, raioPino, 0, Math.PI * 2); ctx.fill() })
    const vivas: typeof bolas = []
    for (const b of bolas) {
      for (let sub = 0; sub < 2; sub++) {
        b.vy += gravidade / 2
        b.x += b.vx / 2
        b.y += b.vy / 2
        for (const p of pinos) {
          const dx = b.x - p.x
          const dy = b.y - p.y
          const dist = Math.hypot(dx, dy)
          const minimo = raioPino + raioBola
          if (dist < minimo && dist > 0) {
            const nx = dx / dist
            const ny = dy / dist
            b.x = p.x + nx * minimo
            b.y = p.y + ny * minimo
            const vn = b.vx * nx + b.vy * ny
            if (vn < 0) {
              b.vx -= 1.55 * vn * nx
              b.vy -= 1.55 * vn * ny
              b.vx += (Math.random() - 0.5) * 0.25
            }
          }
        }
        b.vx *= 0.995
      }
      if (b.y >= inicioCaixas) {
        const i = Math.round((b.x - largura / 2) / espaco + linhas / 2)
        caixas[Math.min(linhas, Math.max(0, i))]++
        total++
        continue
      }
      vivas.push(b)
      ctx.fillStyle = primaria
      ctx.shadowColor = primaria
      ctx.shadowBlur = 8
      ctx.beginPath()
      ctx.arc(b.x, b.y, raioBola, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0
    }
    bolas = vivas
    return { legenda: 'Máquina de Galton: cada bolinha quica ao acaso e, juntas, desenham a curva normal', extra: `${total} bolinhas` }
  }
}

export default function Espera({ titulo, mensagem, desde }: Props) {
  const tela = useRef<HTMLCanvasElement>(null)
  const [cena, setCena] = useState<Cena>('caos')
  const [info, setInfo] = useState({ legenda: '', extra: '' })
  const [agora, setAgora] = useState(Date.now())

  useEffect(() => {
    const troca = window.setTimeout(() => setCena((c) => (c === 'caos' ? 'galton' : 'caos')), 40000)
    return () => window.clearTimeout(troca)
  }, [cena])

  useEffect(() => {
    const canvas = tela.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const escala = window.devicePixelRatio || 1
    const caixa = canvas.getBoundingClientRect()
    canvas.width = caixa.width * escala
    canvas.height = caixa.height * escala
    ctx.scale(escala, escala)
    ctx.fillStyle = cor('--color-surface', '#19181a')
    ctx.fillRect(0, 0, caixa.width, caixa.height)
    const desenhar = cena === 'caos' ? cenaCaos(ctx, caixa.width, caixa.height) : cenaGalton(ctx, caixa.width, caixa.height)
    let quadro = 0
    let pedido = 0
    const laco = () => {
      const r = desenhar()
      if (quadro++ % 15 === 0) { setInfo(r); setAgora(Date.now()) }
      pedido = requestAnimationFrame(laco)
    }
    pedido = requestAnimationFrame(laco)
    return () => cancelAnimationFrame(pedido)
  }, [cena])

  const decorrido = desde ? Math.max(0, Math.round((agora - new Date(desde).getTime()) / 1000)) : null
  return (
    <div className="flex flex-col gap-3 rounded-lg overflow-hidden" style={{ backgroundColor: 'var(--color-surface)', boxShadow: 'var(--shadow-card)' }}>
      <div className="flex flex-wrap items-center gap-3 px-5 pt-5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping" style={{ backgroundColor: 'var(--color-primary)' }} />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full" style={{ backgroundColor: 'var(--color-primary)' }} />
          </span>
          <h2 className="text-base font-semibold">{titulo}</h2>
        </div>
        {decorrido !== null && <span className="text-sm tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{decorrido < 60 ? `${decorrido} s` : `${Math.floor(decorrido / 60)} min ${decorrido % 60} s`}</span>}
        <button
          onClick={() => setCena((c) => (c === 'caos' ? 'galton' : 'caos'))}
          className="ml-auto inline-flex items-center gap-2 h-9 px-3 rounded-md text-sm cursor-pointer"
          style={{ color: 'var(--color-primary-text)', backgroundColor: 'var(--color-primary-bg)' }}
        >
          {cena === 'caos' ? <Sparkles size={16} /> : <Atom size={16} />}
          {cena === 'caos' ? 'Ver a máquina de Galton' : 'Ver o caos dos pêndulos'}
        </button>
      </div>
      {mensagem && <p className="px-5 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{mensagem}</p>}
      <canvas ref={tela} className="w-full h-80 md:h-96 block cursor-pointer" onClick={() => setCena((c) => (c === 'caos' ? 'galton' : 'caos'))} />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{info.legenda}</span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>{info.extra}</span>
      </div>
    </div>
  )
}
