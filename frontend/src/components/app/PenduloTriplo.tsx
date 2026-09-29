import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Volume2, VolumeX } from 'lucide-react'

function cor(nome: string, reserva: string) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nome).trim()
  return v || reserva
}

interface Ponto { x: number; y: number; px: number; py: number }

const ELOS = 3
const PASSOS = 8
const CHAVE_PASSAROS = 'pendulo-passaros-recorde'

interface Passaro { x: number; y: number; vx: number; fase: number; baseY: number; caindo: boolean; vy: number; giro: number; vida: number }
interface Pena { x: number; y: number; vx: number; vy: number; giro: number; vida: number }

const CHAVE_SOM = 'pendulo-som-mudo'

function lerMudo() {
  try { return localStorage.getItem(CHAVE_SOM) === '1' } catch { return false }
}

interface Som { ativar: () => void; acerto: () => void; vento: (velocidade: number) => void; mudar: (mudo: boolean) => void; fechar: () => void }

function criarSom(mudoInicial: boolean): Som {
  let audio: AudioContext | null = null
  let mestre: GainNode | null = null
  let ventoGanho: GainNode | null = null
  let ventoFiltro: BiquadFilterNode | null = null
  let ruido: AudioBuffer | null = null
  let mudo = mudoInicial

  const ativar = () => {
    if (audio) { if (audio.state === 'suspended') void audio.resume(); return }
    const Construtor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Construtor) return
    audio = new Construtor()
    mestre = audio.createGain()
    mestre.gain.value = mudo ? 0 : 1
    mestre.connect(audio.destination)
    ruido = audio.createBuffer(1, audio.sampleRate * 2, audio.sampleRate)
    const dados = ruido.getChannelData(0)
    let marrom = 0
    for (let i = 0; i < dados.length; i++) {
      marrom = (marrom + 0.02 * (Math.random() * 2 - 1)) / 1.02
      dados[i] = marrom * 3.5
    }
    const fonte = audio.createBufferSource()
    fonte.buffer = ruido
    fonte.loop = true
    ventoFiltro = audio.createBiquadFilter()
    ventoFiltro.type = 'bandpass'
    ventoFiltro.frequency.value = 300
    ventoFiltro.Q.value = 0.8
    ventoGanho = audio.createGain()
    ventoGanho.gain.value = 0
    fonte.connect(ventoFiltro).connect(ventoGanho).connect(mestre)
    fonte.start()
  }

  const vento = (velocidade: number) => {
    if (!audio || !ventoGanho || !ventoFiltro) return
    const forca = Math.min(1, Math.max(0, (velocidade - 60) / 1400))
    const agora = audio.currentTime
    ventoGanho.gain.setTargetAtTime(forca * forca * 0.55, agora, 0.08)
    ventoFiltro.frequency.setTargetAtTime(250 + forca * 1600, agora, 0.1)
    ventoFiltro.Q.setTargetAtTime(0.7 + forca * 2.5, agora, 0.1)
  }

  const acerto = () => {
    if (!audio || !mestre || !ruido) return
    const agora = audio.currentTime
    const pio = audio.createOscillator()
    const pioGanho = audio.createGain()
    pio.type = 'triangle'
    pio.frequency.setValueAtTime(1300, agora)
    pio.frequency.exponentialRampToValueAtTime(2600, agora + 0.05)
    pio.frequency.exponentialRampToValueAtTime(700, agora + 0.18)
    pioGanho.gain.setValueAtTime(0.0001, agora)
    pioGanho.gain.exponentialRampToValueAtTime(0.35, agora + 0.01)
    pioGanho.gain.exponentialRampToValueAtTime(0.0001, agora + 0.2)
    pio.connect(pioGanho).connect(mestre)
    pio.start(agora)
    pio.stop(agora + 0.22)

    const baque = audio.createOscillator()
    const baqueGanho = audio.createGain()
    baque.type = 'sine'
    baque.frequency.setValueAtTime(220, agora)
    baque.frequency.exponentialRampToValueAtTime(60, agora + 0.15)
    baqueGanho.gain.setValueAtTime(0.5, agora)
    baqueGanho.gain.exponentialRampToValueAtTime(0.0001, agora + 0.18)
    baque.connect(baqueGanho).connect(mestre)
    baque.start(agora)
    baque.stop(agora + 0.2)

    const estalo = audio.createBufferSource()
    estalo.buffer = ruido
    const estaloFiltro = audio.createBiquadFilter()
    estaloFiltro.type = 'highpass'
    estaloFiltro.frequency.value = 1500
    const estaloGanho = audio.createGain()
    estaloGanho.gain.setValueAtTime(0.6, agora)
    estaloGanho.gain.exponentialRampToValueAtTime(0.0001, agora + 0.08)
    estalo.connect(estaloFiltro).connect(estaloGanho).connect(mestre)
    estalo.start(agora, Math.random())
    estalo.stop(agora + 0.1)
  }

  const mudar = (valor: boolean) => {
    mudo = valor
    if (audio && mestre) mestre.gain.setTargetAtTime(valor ? 0 : 1, audio.currentTime, 0.03)
  }

  const fechar = () => { void audio?.close(); audio = null }

  return { ativar, acerto, vento, mudar, fechar }
}

function lerRecordePassaros() {
  try { return Number(localStorage.getItem(CHAVE_PASSAROS)) || 0 } catch { return 0 }
}

export default function PenduloTriplo() {
  const tela = useRef<HTMLCanvasElement>(null)
  const teclas = useRef({ esquerda: false, direita: false })
  const arrasto = useRef<number | null>(null)
  const [recorde, setRecorde] = useState(0)
  const [equilibrio, setEquilibrio] = useState(0)
  const [passaros, setPassaros] = useState({ pontos: 0, recorde: lerRecordePassaros() })
  const [mudo, setMudo] = useState(lerMudo)
  const som = useRef<Som | null>(null)
  if (!som.current) som.current = criarSom(mudo)

  useEffect(() => {
    const atual = som.current
    return () => atual?.fechar()
  }, [])

  const alternarSom = () => {
    const novo = !mudo
    setMudo(novo)
    som.current?.ativar()
    som.current?.mudar(novo)
    try { localStorage.setItem(CHAVE_SOM, novo ? '1' : '0') } catch { /* sem armazenamento */ }
  }

  useEffect(() => {
    const baixo = (e: KeyboardEvent) => {
      if (['ArrowLeft', 'ArrowRight', 'a', 'd'].includes(e.key)) som.current?.ativar()
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
    const perigo = cor('--color-danger', '#c62f2a')
    const sucesso = cor('--color-success', '#0f7a52')

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
    const bandos: Passaro[] = []
    const penas: Pena[] = []
    const avisos: { x: number; y: number; vida: number }[] = []
    let proximoPassaro = 0.8
    let velocidadePonta = 0
    let pontosPassaros = 0
    let recordePassaros = lerRecordePassaros()
    const alcanceTopo = Math.max(36, trilhoY - ELOS * comprimento - 10)
    const alcanceBase = trilhoY - comprimento * 0.6

    function novoPassaro() {
      const daEsquerda = Math.random() < 0.5
      const baseY = alcanceTopo + Math.random() * (alcanceBase - alcanceTopo)
      const velocidade = 70 + Math.random() * 80 + Math.min(80, pontosPassaros * 4)
      bandos.push({ x: daEsquerda ? -30 : largura + 30, y: baseY, baseY, vx: daEsquerda ? velocidade : -velocidade, fase: Math.random() * Math.PI * 2, caindo: false, vy: 0, giro: 0, vida: 1 })
    }

    function desenharPassaro(b: Passaro, agora: number) {
      const asa = b.caindo ? 0.2 : Math.sin(agora / 70 + b.fase)
      const lado = b.vx >= 0 ? 1 : -1
      ctx!.save()
      ctx!.translate(b.x, b.y)
      ctx!.rotate(b.giro)
      ctx!.scale(lado, 1)
      ctx!.globalAlpha = b.vida
      ctx!.fillStyle = b.caindo ? perigo : texto
      ctx!.beginPath(); ctx!.ellipse(0, 0, 11, 6.5, 0, 0, Math.PI * 2); ctx!.fill()
      ctx!.beginPath(); ctx!.arc(9, -3, 4.5, 0, Math.PI * 2); ctx!.fill()
      ctx!.fillStyle = primaria
      ctx!.beginPath(); ctx!.moveTo(13, -3); ctx!.lineTo(18, -1.5); ctx!.lineTo(13, 0); ctx!.closePath(); ctx!.fill()
      ctx!.beginPath(); ctx!.moveTo(-10, 0); ctx!.lineTo(-17, -4); ctx!.lineTo(-16, 3); ctx!.closePath(); ctx!.fillStyle = b.caindo ? perigo : texto; ctx!.fill()
      ctx!.strokeStyle = b.caindo ? perigo : texto
      ctx!.lineWidth = 2.5
      ctx!.lineCap = 'round'
      ctx!.beginPath(); ctx!.moveTo(-3, -2); ctx!.quadraticCurveTo(-4, -2 - asa * 10, -12, -4 - asa * 13); ctx!.stroke()
      ctx!.fillStyle = fundo
      ctx!.beginPath(); ctx!.arc(10.5, -4, 1.4, 0, Math.PI * 2); ctx!.fill()
      if (b.caindo) {
        ctx!.strokeStyle = fundo
        ctx!.lineWidth = 1.2
        ctx!.beginPath(); ctx!.moveTo(9, -5.5); ctx!.lineTo(12, -2.5); ctx!.moveTo(12, -5.5); ctx!.lineTo(9, -2.5); ctx!.stroke()
      }
      ctx!.restore()
    }

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
      const anteriorPonta = rastro[rastro.length - 1]
      if (anteriorPonta && dt > 0) velocidadePonta += (Math.hypot(ponta.x - anteriorPonta.x, ponta.y - anteriorPonta.y) / dt - velocidadePonta) * Math.min(1, dt * 10)
      som.current?.vento(velocidadePonta)
      rastro.push({ x: ponta.x, y: ponta.y })
      if (rastro.length > 140) rastro.shift()
      const emPe = pontos.every((p, i) => p.y < trilhoY - (i + 1) * comprimento * 0.8)
      tempoEmPe = emPe ? tempoEmPe + dt : 0
      if (tempoEmPe > melhor) melhor = tempoEmPe

      proximoPassaro -= dt
      if (proximoPassaro <= 0 && bandos.filter((b) => !b.caindo).length < 4) {
        novoPassaro()
        proximoPassaro = Math.max(0.7, 2.2 - pontosPassaros * 0.06) + Math.random() * 1.2
      }
      for (let k = bandos.length - 1; k >= 0; k--) {
        const b = bandos[k]
        if (b.caindo) {
          b.vy += 900 * dt
          b.y += b.vy * dt
          b.x += b.vx * 0.25 * dt
          b.giro += dt * 7 * Math.sign(b.vx || 1)
          if (b.y > trilhoY) b.vida -= dt * 3
          if (b.vida <= 0 || b.y > altura + 30) bandos.splice(k, 1)
          continue
        }
        b.x += b.vx * dt
        b.y = b.baseY + Math.sin(agora / 400 + b.fase) * 14
        if (Math.hypot(ponta.x - b.x, ponta.y - b.y) < 22) {
          b.caindo = true
          b.vy = -120
          som.current?.acerto()
          pontosPassaros += 1
          if (pontosPassaros > recordePassaros) {
            recordePassaros = pontosPassaros
            try { localStorage.setItem(CHAVE_PASSAROS, String(recordePassaros)) } catch { /* sem armazenamento */ }
          }
          setPassaros({ pontos: pontosPassaros, recorde: recordePassaros })
          avisos.push({ x: b.x, y: b.y - 18, vida: 1 })
          for (let q = 0; q < 10; q++) penas.push({ x: b.x, y: b.y, vx: (Math.random() - 0.5) * 160, vy: -Math.random() * 120, giro: Math.random() * Math.PI, vida: 1 })
          continue
        }
        if (b.x < -60 || b.x > largura + 60) bandos.splice(k, 1)
      }

      ctx.fillStyle = fundo
      ctx.fillRect(0, 0, largura, altura)
      for (const b of bandos) desenharPassaro(b, agora)
      for (let k = penas.length - 1; k >= 0; k--) {
        const f = penas[k]
        f.vy += 120 * dt; f.vx *= Math.pow(0.3, dt); f.x += f.vx * dt + Math.sin(agora / 150 + k) * 0.6; f.y += f.vy * dt; f.giro += dt * 3; f.vida -= dt * 0.8
        if (f.vida <= 0) { penas.splice(k, 1); continue }
        ctx.save()
        ctx.globalAlpha = f.vida
        ctx.translate(f.x, f.y)
        ctx.rotate(f.giro)
        ctx.fillStyle = secundario
        ctx.beginPath(); ctx.ellipse(0, 0, 5, 1.8, 0, 0, Math.PI * 2); ctx.fill()
        ctx.restore()
      }
      for (let k = avisos.length - 1; k >= 0; k--) {
        const a = avisos[k]
        a.y -= dt * 40; a.vida -= dt * 1.2
        if (a.vida <= 0) { avisos.splice(k, 1); continue }
        ctx.globalAlpha = a.vida
        ctx.fillStyle = sucesso
        ctx.font = '700 16px Figtree, sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText('+1', a.x, a.y)
        ctx.textAlign = 'left'
      }
      ctx.globalAlpha = 1
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
      ctx.font = '14px Figtree, sans-serif'
      ctx.textAlign = 'left'
      ctx.fillText(emPe ? `Em pé há ${tempoEmPe.toFixed(1)} s` : 'Acerte os passarinhos com a ponta do pêndulo', 20, 28)
      ctx.textAlign = 'right'
      ctx.fillStyle = texto
      ctx.font = '600 16px Figtree, sans-serif'
      ctx.fillText(`${pontosPassaros} ${pontosPassaros === 1 ? 'passarinho' : 'passarinhos'}`, largura - 20, 28)
      ctx.textAlign = 'left'

      if (quadro++ % 20 === 0) { setRecorde(melhor); setEquilibrio(tempoEmPe) }
      pedido = requestAnimationFrame(laco)
    }
    pedido = requestAnimationFrame(laco)
    return () => { cancelAnimationFrame(pedido); som.current?.vento(0) }
  }, [])

  const posicao = (e: React.PointerEvent<HTMLCanvasElement>) => e.clientX - e.currentTarget.getBoundingClientRect().left
  const segurar = (lado: 'esquerda' | 'direita', valor: boolean) => { teclas.current[lado] = valor }

  return (
    <>
      <canvas
        ref={tela}
        className="w-full h-96 md:h-[32rem] block cursor-grab touch-none"
        onPointerDown={(e) => { som.current?.ativar(); arrasto.current = posicao(e); e.currentTarget.setPointerCapture(e.pointerId) }}
        onPointerMove={(e) => { if (arrasto.current !== null) arrasto.current = posicao(e) }}
        onPointerUp={() => { arrasto.current = null }}
        onPointerCancel={() => { arrasto.current = null }}
      />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Mova o carrinho com as setas ← → (ou arraste) e acerte os passarinhos com a ponta do pêndulo{equilibrio > 0 ? ` · ${equilibrio.toFixed(1)} s em pé` : ''}
        </span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>
          {passaros.pontos} {passaros.pontos === 1 ? 'passarinho' : 'passarinhos'} · recorde {passaros.recorde} · em pé {recorde.toFixed(1)} s
        </span>
        <button
          onClick={alternarSom}
          aria-label={mudo ? 'Ligar o som' : 'Desligar o som'}
          title={mudo ? 'Ligar o som' : 'Desligar o som'}
          className="h-10 md:h-9 w-10 md:w-9 inline-flex items-center justify-center rounded-md cursor-pointer"
          style={{ backgroundColor: 'var(--color-primary-bg)', color: 'var(--color-primary-text)' }}
        >
          {mudo ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <div className="flex gap-2 md:hidden">
          {(['esquerda', 'direita'] as const).map((lado) => (
            <button key={lado} className="h-10 w-10 inline-flex items-center justify-center rounded-md cursor-pointer" style={{ backgroundColor: 'var(--color-primary-bg)', color: 'var(--color-primary-text)' }}
              onPointerDown={() => { som.current?.ativar(); segurar(lado, true) }} onPointerUp={() => segurar(lado, false)} onPointerLeave={() => segurar(lado, false)} aria-label={lado === 'esquerda' ? 'Mover para a esquerda' : 'Mover para a direita'}>
              {lado === 'esquerda' ? <ArrowLeft size={18} /> : <ArrowRight size={18} />}
            </button>
          ))}
        </div>
      </div>
    </>
  )
}
