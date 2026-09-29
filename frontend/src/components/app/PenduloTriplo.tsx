import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight } from 'lucide-react'

function cor(nome: string, reserva: string) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome).trim()
  return v || reserva
}

interface Ponto { x: number; y: number; px: number; py: number }

const ELOS = 3
const PASSOS = 8

export default function PenduloTriplo() {
  const tela = useRef<HTMLCanvasElement>(null)
  const teclas = useRef({ esquerda: false, direita: false })
  const arrasto = useRef<number | null>(null)
  const [recorde, setRecorde] = useState(0)
  const [equilibrio, setEquilibrio] = useState(0)

  useEffect(() => {
    const baixo = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' || e.key === 'a') { teclas.current.esquerda = true; e.preventDefault() }
      if (e.key === 'ArrowRight' || e.key === 'd') { teclas.current.direita = true; e.preventDefault() }
    }
    const cima = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft' || e.key === 'a') teclas.current.esquerda = false
      if (e.key === 'ArrowRight' || e.key === 'd') teclas.current.direita = false
    }
    window.addEventListener('keydown', baixo)
    window.addEventListener('keyup', cima)
    return () => { window.removeEventListener('keydown', baixo); window.removeEventListener('keyup', cima) }
  }, [])

  useEffect(() => {
    const canvas = tela.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const escala = window.devicePixelRatio || 1
    const caixa = canvas.getBoundingClientRect()
    const largura = caixa.width
    const altura = caixa.height
    canvas.width = largura * escala
    canvas.height = altura * escala
    ctx.scale(escala, escala)

    const primaria = cor('--color-primary', '#c8f031')
    const texto = cor('--color-text', '#f2f2f2')
    const secundario = cor('--color-text-secondary', '#9a9a9a')
    const fundo = cor('--color-surface', '#19181a')
    const borda = cor('--color-border', '#333333')

    const trilhoY = Math.round(altura / 2) + 10
    const comprimento = Math.min(altura - trilhoY - 24, trilhoY - 44, 240) / ELOS
    let carroX = largura / 2
    let carroV = 0
    const pontos: Ponto[] = []
    for (let i = 1; i <= ELOS; i++) {
      const x = carroX + (i * 3)
      const y = trilhoY - i * comprimento
      pontos.push({ x, y, px: x, py: y })
    }
    const rastro: { x: number; y: number }[] = []
    let tempoEmPe = 0
    let melhor = 0
    let quadro = 0
    let ultimo = performance.now()
    let pedido = 0

    const laco = (agora: number) => {
      const dt = Math.min(0.033, (agora - ultimo) / 1000)
      ultimo = agora
      const aceleracao = 2600
      let alvoV = carroV
      if (arrasto.current !== null) {
        alvoV = (arrasto.current - carroX) * 12
      } else {
        if (teclas.current.esquerda) alvoV -= aceleracao * dt
        if (teclas.current.direita) alvoV += aceleracao * dt
        if (!teclas.current.esquerda && !teclas.current.direita) alvoV *= Math.pow(0.02, dt)
      }
      carroV = Math.max(-900, Math.min(900, alvoV))
      carroX += carroV * dt
      if (carroX < 40) { carroX = 40; carroV = 0 }
      if (carroX > largura - 40) { carroX = largura - 40; carroV = 0 }

      const sub = dt / PASSOS
      const gravidade = 1400
      for (let passo = 0; passo < PASSOS; passo++) {
        for (const p of pontos) {
          const vx = (p.x - p.px) * 0.9995
          const vy = (p.y - p.py) * 0.9995
          p.px = p.x; p.py = p.y
          p.x += vx
          p.y += vy + gravidade * sub * sub
        }
        for (let iter = 0; iter < 6; iter++) {
          let ax = carroX
          let ay = trilhoY
          for (let i = 0; i < ELOS; i++) {
            const p = pontos[i]
            const dx = p.x - ax
            const dy = p.y - ay
            const d = Math.hypot(dx, dy) || 1
            const erro = (d - comprimento) / d
            if (i === 0) {
              p.x -= dx * erro; p.y -= dy * erro
            } else {
              const q = pontos[i - 1]
              p.x -= dx * erro * 0.5; p.y -= dy * erro * 0.5
              q.x += dx * erro * 0.5; q.y += dy * erro * 0.5
            }
            ax = p.x; ay = p.y
          }
        }
      }

      const ponta = pontos[ELOS - 1]
      rastro.push({ x: ponta.x, y: ponta.y })
      if (rastro.length > 140) rastro.shift()
      const emPe = pontos.every((p, i) => p.y < trilhoY - (i + 1) * comprimento * 0.8)
      tempoEmPe = emPe ? tempoEmPe + dt : 0
      if (tempoEmPe > melhor) melhor = tempoEmPe

      ctx.fillStyle = fundo
      ctx.fillRect(0, 0, largura, altura)
      ctx.strokeStyle = borda
      ctx.lineWidth = 2
      ctx.beginPath(); ctx.moveTo(24, trilhoY + 14); ctx.lineTo(largura - 24, trilhoY + 14); ctx.stroke()

      for (let i = 1; i < rastro.length; i++) {
        ctx.strokeStyle = primaria
        ctx.globalAlpha = (i / rastro.length) * 0.6
        ctx.lineWidth = 2
        ctx.beginPath(); ctx.moveTo(rastro[i - 1].x, rastro[i - 1].y); ctx.lineTo(rastro[i].x, rastro[i].y); ctx.stroke()
      }
      ctx.globalAlpha = 1

      ctx.strokeStyle = texto
      ctx.lineWidth = 3
      ctx.beginPath(); ctx.moveTo(carroX, trilhoY)
      for (const p of pontos) ctx.lineTo(p.x, p.y)
      ctx.stroke()
      pontos.forEach((p, i) => {
        ctx.fillStyle = i === ELOS - 1 ? primaria : texto
        ctx.beginPath(); ctx.arc(p.x, p.y, i === ELOS - 1 ? 9 : 7, 0, Math.PI * 2); ctx.fill()
      })

      ctx.fillStyle = primaria
      ctx.beginPath()
      ctx.roundRect(carroX - 34, trilhoY - 10, 68, 22, 6)
      ctx.fill()
      ctx.fillStyle = fundo
      ctx.beginPath(); ctx.arc(carroX, trilhoY, 4, 0, Math.PI * 2); ctx.fill()

      ctx.fillStyle = secundario
      ctx.font = '14px Manrope, Figtree, sans-serif'
      ctx.fillText(emPe ? `Em pé há ${tempoEmPe.toFixed(1)} s` : 'Tente deixar os três elos em pé', 20, 28)

      if (quadro++ % 20 === 0) { setRecorde(melhor); setEquilibrio(tempoEmPe) }
      pedido = requestAnimationFrame(laco)
    }
    pedido = requestAnimationFrame(laco)
    return () => cancelAnimationFrame(pedido)
  }, [])

  const posicao = (e: React.PointerEvent<HTMLCanvasElement>) => e.clientX - e.currentTarget.getBoundingClientRect().left
  const segurar = (lado: 'esquerda' | 'direita', valor: boolean) => { teclas.current[lado] = valor }

  return (
    <>
      <canvas
        ref={tela}
        className="w-full h-96 md:h-[32rem] block cursor-grab touch-none"
        onPointerDown={(e) => { arrasto.current = posicao(e); e.currentTarget.setPointerCapture(e.pointerId) }}
        onPointerMove={(e) => { if (arrasto.current !== null) arrasto.current = posicao(e) }}
        onPointerUp={() => { arrasto.current = null }}
        onPointerCancel={() => { arrasto.current = null }}
      />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Pêndulo triplo: use as setas ← → do teclado (ou arraste) para mover o carrinho{equilibrio > 0 ? ` · ${equilibrio.toFixed(1)} s em pé` : ''}
        </span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>Recorde em pé: {recorde.toFixed(1)} s</span>
        <div className="flex gap-2 md:hidden">
          {(['esquerda', 'direita'] as const).map((lado) => (
            <button key={lado} className="h-10 w-10 inline-flex items-center justify-center rounded-md cursor-pointer" style={{ backgroundColor: 'var(--color-primary-bg)', color: 'var(--color-primary-text)' }}
              onPointerDown={() => segurar(lado, true)} onPointerUp={() => segurar(lado, false)} onPointerLeave={() => segurar(lado, false)} aria-label={lado === 'esquerda' ? 'Mover para a esquerda' : 'Mover para a direita'}>
              {lado === 'esquerda' ? <ArrowLeft size={18} /> : <ArrowRight size={18} />}
            </button>
          ))}
        </div>
      </div>
    </>
  )
}
