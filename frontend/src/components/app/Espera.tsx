import { useEffect, useRef, useState } from 'react'
import { SkipForward } from 'lucide-react'
import PenduloTriplo from './PenduloTriplo'
import NuvensMatematica from './NuvensMatematica'
import BarcosTabuada from './BarcosTabuada'

export type Cena = 'barcos' | 'pendulo' | 'nuvens' | 'caos' | 'galton'
export const CENAS: Cena[] = ['barcos', 'pendulo', 'nuvens', 'galton', 'caos']
export const NOMES: Record<Cena, string> = { barcos: 'barcos da tabuada', pendulo: 'pêndulo triplo', nuvens: 'pulo nas nuvens', caos: 'caos dos pêndulos', galton: 'máquina de Galton' }

interface Props { titulo: string; mensagem?: string | null; desde?: string | null; cenaInicial?: Cena }

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
  const curva = cor('--color-danger', '#ef4444')
  const cinza = rgb(cor('--color-text-secondary', '#a9ad9b'))
  const fundo = cor('--color-surface', '#19181a')
  const tom = (a: number) => `rgba(${cinza[0]},${cinza[1]},${cinza[2]},${a})`
  const linhas = 9
  const caixasN = linhas + 1
  const espaco = Math.min(largura * 0.8 / caixasN, altura / 11.5)
  const cx = largura / 2
  const raioPino = espaco * 0.2
  const raioBola = Math.max(2.2, espaco * 0.085)
  const funilTopo = espaco * 0.3
  const funilBoca = espaco * 1.7
  const funilLargura = espaco * 3.2
  const pinosTopo = funilBoca + espaco * 0.8
  const passoY = espaco * 0.62
  const pinos: { x: number; y: number }[] = []
  for (let r = 0; r < linhas; r++) for (let c = 0; c <= r; c++) pinos.push({ x: cx + (c - r / 2) * espaco, y: pinosTopo + r * passoY })
  const caixasTopo = pinosTopo + linhas * passoY + espaco * 0.2
  const chao = altura - 8
  const esquerda = cx - (caixasN / 2) * espaco
  const pilhas: number[] = new Array(caixasN).fill(0)
  const porLinha = Math.max(1, Math.floor(espaco / (raioBola * 2.1)))
  const capacidade = porLinha * Math.floor((chao - caixasTopo) / (raioBola * 1.85))
  let bolas: { x: number; y: number; vx: number; vy: number }[] = []
  const reserva = Array.from({ length: 70 }, () => ({ x: cx + (Math.random() - 0.5) * funilLargura * 1.5, y: funilTopo + Math.random() * (funilBoca - funilTopo) * 0.7 }))
  let total = 0
  let quadro = 0
  const gravidade = espaco * 0.012
  function paredeFunil(y: number) {
    const p = Math.min(1, Math.max(0, (y - funilTopo) / (funilBoca - funilTopo)))
    return funilLargura * (1 - p) + raioBola * 1.4 * p
  }
  return () => {
    quadro++
    if (quadro % 5 === 0 && bolas.length < 90) bolas.push({ x: cx + (Math.random() - 0.5) * 0.4, y: funilBoca, vx: 0, vy: 0.5 })
    if (pilhas.some((n) => n >= capacidade)) { pilhas.fill(0); total = 0 }
    ctx.fillStyle = fundo
    ctx.fillRect(0, 0, largura, altura)

    ctx.strokeStyle = tom(0.55)
    ctx.lineWidth = 3
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.moveTo(cx - funilLargura - espaco * 0.3, funilTopo - espaco * 0.2)
    ctx.quadraticCurveTo(cx - funilLargura, funilTopo + espaco * 0.4, cx - raioBola * 1.4, funilBoca)
    ctx.moveTo(cx + funilLargura + espaco * 0.3, funilTopo - espaco * 0.2)
    ctx.quadraticCurveTo(cx + funilLargura, funilTopo + espaco * 0.4, cx + raioBola * 1.4, funilBoca)
    ctx.stroke()
    ctx.fillStyle = primaria
    for (const r of reserva) {
      const limite = paredeFunil(r.y) - raioBola
      const x = Math.max(cx - limite, Math.min(cx + limite, r.x))
      ctx.beginPath(); ctx.arc(x, r.y, raioBola, 0, Math.PI * 2); ctx.fill()
    }

    ctx.fillStyle = tom(0.35)
    for (const p of pinos) { ctx.beginPath(); ctx.arc(p.x, p.y, raioPino, 0, Math.PI * 2); ctx.fill() }

    ctx.strokeStyle = tom(0.5)
    ctx.lineWidth = 2
    ctx.beginPath()
    for (let i = 0; i <= caixasN; i++) { const x = esquerda + i * espaco; ctx.moveTo(x, caixasTopo); ctx.lineTo(x, chao) }
    ctx.moveTo(esquerda, chao); ctx.lineTo(esquerda + caixasN * espaco, chao)
    ctx.stroke()

    ctx.fillStyle = primaria
    pilhas.forEach((n, i) => {
      for (let k = 0; k < n; k++) {
        const linha = Math.floor(k / porLinha)
        const coluna = k % porLinha
        const desloc = linha % 2 ? raioBola : 0
        const x = esquerda + i * espaco + raioBola * 1.2 + desloc + coluna * raioBola * 2.05
        const y = chao - raioBola - 1 - linha * raioBola * 1.8
        if (x > esquerda + (i + 1) * espaco - raioBola) continue
        ctx.beginPath(); ctx.arc(x, y, raioBola, 0, Math.PI * 2); ctx.fill()
      }
    })

    const vivas: typeof bolas = []
    for (const b of bolas) {
      for (let sub = 0; sub < 3; sub++) {
        b.vy += gravidade / 3
        b.x += b.vx / 3
        b.y += b.vy / 3
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
            if (vn < 0) { b.vx -= 1.4 * vn * nx; b.vy -= 1.4 * vn * ny }
            if (Math.abs(dx) < raioBola * 0.4) b.vx += (Math.random() < 0.5 ? -1 : 1) * espaco * 0.03
          }
        }
        b.vx *= 0.985
      }
      if (b.y >= caixasTopo) {
        const i = Math.min(caixasN - 1, Math.max(0, Math.floor((b.x - esquerda) / espaco)))
        const alvoY = chao - raioBola - Math.floor(pilhas[i] / porLinha) * raioBola * 1.8
        b.x = Math.max(esquerda + i * espaco + raioBola + 1, Math.min(esquerda + (i + 1) * espaco - raioBola - 1, b.x))
        b.vx = 0
        if (b.y >= alvoY) { pilhas[i]++; total++; continue }
      }
      vivas.push(b)
      ctx.fillStyle = primaria
      ctx.beginPath(); ctx.arc(b.x, b.y, raioBola, 0, Math.PI * 2); ctx.fill()
    }
    bolas = vivas

    if (total > 20) {
      const media = linhas / 2
      const desvio = Math.sqrt(linhas / 4)
      const pico = total / (desvio * Math.sqrt(2 * Math.PI))
      const alturaLinha = (raioBola * 1.8) / porLinha
      ctx.strokeStyle = curva
      ctx.lineWidth = 4
      ctx.beginPath()
      for (let k = 0; k <= 200; k++) {
        const i = -0.5 + (k / 200) * caixasN
        const dens = pico * Math.exp(-((i - media) ** 2) / (2 * desvio * desvio))
        const x = esquerda + (i + 0.5) * espaco
        const y = Math.max(caixasTopo, chao - dens * alturaLinha)
        if (k === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()
    }
    return { legenda: 'Máquina de Galton: cada bolinha escolhe esquerda ou direita ao acaso e, juntas, desenham a curva normal', extra: `${total} bolinhas` }
  }
}

function CenaCanvas({ cena }: { cena: 'caos' | 'galton' }) {
  const tela = useRef<HTMLCanvasElement>(null)
  const [info, setInfo] = useState({ legenda: '', extra: '' })

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
      if (quadro++ % 15 === 0) setInfo(r)
      pedido = requestAnimationFrame(laco)
    }
    pedido = requestAnimationFrame(laco)
    return () => cancelAnimationFrame(pedido)
  }, [cena])

  return (
    <>
      <canvas ref={tela} className="w-full h-96 md:h-[32rem] block" />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{info.legenda}</span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>{info.extra}</span>
      </div>
    </>
  )
}

export function ConteudoCena({ cena }: { cena: Cena }) {
  return cena === 'barcos' ? <BarcosTabuada /> : cena === 'pendulo' ? <PenduloTriplo /> : cena === 'nuvens' ? <NuvensMatematica /> : <CenaCanvas key={cena} cena={cena} />
}

function duracao(segundos: number) {
  return segundos < 60 ? `${segundos} s` : `${Math.floor(segundos / 60)} min ${String(segundos % 60).padStart(2, '0')} s`
}

export default function Espera({ titulo, mensagem, desde, cenaInicial }: Props) {
  const [cena, setCena] = useState<Cena>(cenaInicial || 'barcos')
  const [agora, setAgora] = useState(Date.now())
  const montado = useRef(Date.now())

  useEffect(() => {
    const relogio = window.setInterval(() => setAgora(Date.now()), 1000)
    return () => window.clearInterval(relogio)
  }, [])

  const inicio = desde ? new Date(desde).getTime() : NaN
  const base = Number.isFinite(inicio) ? Math.min(inicio, montado.current) : montado.current
  const decorrido = Math.max(0, Math.round((agora - base) / 1000))
  const proxima = CENAS[(CENAS.indexOf(cena) + 1) % CENAS.length]
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
        <span className="text-sm tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>{duracao(decorrido)}</span>
        <button
          onClick={() => setCena(proxima)}
          title={`Próximo: ${NOMES[proxima]}`}
          className="ml-auto inline-flex items-center gap-2 h-9 px-3 rounded-md text-sm cursor-pointer"
          style={{ color: 'var(--color-primary-text)', backgroundColor: 'var(--color-primary-bg)' }}
        >
          <SkipForward size={16} /> Próximo
        </button>
      </div>
      {mensagem && <p className="px-5 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{mensagem}</p>}
      <ConteudoCena cena={cena} />
    </div>
  )
}
