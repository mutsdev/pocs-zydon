import { useEffect, useRef, useState } from 'react'

function cor(nome: string, reserva: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(nome).trim() || reserva
}

interface Pergunta { texto: string; resposta: number; opcoes: number[] }

function sortear(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1))
}

function novaPergunta(nivel: number): Pergunta {
  const tipo = nivel < 2 ? sortear(0, 1) : nivel < 5 ? sortear(0, 2) : sortear(0, 3)
  const teto = 10 + nivel * 6
  let a = sortear(2, teto)
  let b = sortear(2, teto)
  let texto = ''
  let resposta = 0
  if (tipo === 0) { texto = `${a} + ${b}`; resposta = a + b }
  else if (tipo === 1) { if (b > a) [a, b] = [b, a]; texto = `${a} − ${b}`; resposta = a - b }
  else if (tipo === 2) { a = sortear(2, 5 + nivel); b = sortear(2, 9); texto = `${a} × ${b}`; resposta = a * b }
  else { b = sortear(2, 9); resposta = sortear(2, 5 + nivel); texto = `${b * resposta} ÷ ${b}`; a = b * resposta }
  const opcoes = new Set<number>([resposta])
  while (opcoes.size < 3) {
    const erro = resposta + (Math.random() < 0.5 ? -1 : 1) * sortear(1, Math.max(3, Math.round(resposta * 0.2)))
    if (erro >= 0) opcoes.add(erro)
  }
  return { texto, resposta, opcoes: [...opcoes].sort(() => Math.random() - 0.5) }
}

type Fase = 'pergunta' | 'pulo' | 'erro' | 'queda'

export default function NuvensMatematica() {
  const tela = useRef<HTMLCanvasElement>(null)
  const [placar, setPlacar] = useState({ pontos: 0, sequencia: 0, recorde: 0 })
  const escolher = useRef<(i: number) => void>(() => {})

  useEffect(() => {
    const canvas = tela.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const escala = window.devicePixelRatio || 1
    const caixa = canvas.getBoundingClientRect()
    const L = caixa.width
    const A = caixa.height
    canvas.width = L * escala
    canvas.height = A * escala
    ctx.scale(escala, escala)
    const primaria = cor('--color-primary', '#cdeb00')
    const naPrimaria = cor('--color-on-primary', '#111')
    const fundo = cor('--color-surface', '#19181a')
    const textoCor = cor('--color-text', '#f2f2f2')
    const secundario = cor('--color-text-secondary', '#a9ad9b')
    const perigo = cor('--color-danger', '#ef4444')
    const salto = Math.min(150, A * 0.36)
    const baseY = A - 60
    const colunas = [L * 0.2, L * 0.5, L * 0.8]

    let pontos = 0
    let sequencia = 0
    let recorde = 0
    let nivel = 0
    let pergunta = novaPergunta(0)
    let fase: Fase = 'pergunta'
    let atual = 1
    let t = 0
    let progresso = 0
    let limite = 9
    const limitePara = (n: number) => Math.max(2.8, 9 * Math.pow(0.94, n))
    let camera = 0
    let errada = -1
    let destino = 1
    const estrelas = Array.from({ length: 50 }, () => ({ x: Math.random() * L, y: Math.random() * A * 3, r: Math.random() * 1.4 + 0.3 }))
    const particulas: { x: number; y: number; vx: number; vy: number; vida: number }[] = []

    function nuvem(x: number, y: number, largura: number, alfa: number, destaque: boolean) {
      ctx!.save()
      ctx!.globalAlpha = alfa
      ctx!.fillStyle = destaque ? primaria : textoCor
      const partes: [number, number, number][] = [[-0.32, 0.08, 0.26], [-0.1, -0.12, 0.3], [0.16, -0.06, 0.27], [0.36, 0.1, 0.2], [0, 0.12, 0.3]]
      ctx!.beginPath()
      for (const [dx, dy, r] of partes) {
        ctx!.moveTo(x + dx * largura + r * largura, y + dy * largura)
        ctx!.arc(x + dx * largura, y + dy * largura, r * largura, 0, Math.PI * 2)
      }
      ctx!.fill()
      ctx!.restore()
    }

    function heroi(x: number, y: number, esticar: number) {
      ctx!.save()
      ctx!.translate(x, y)
      ctx!.scale(1 - esticar * 0.15, 1 + esticar * 0.2)
      ctx!.fillStyle = primaria
      ctx!.shadowColor = primaria
      ctx!.shadowBlur = 14
      ctx!.beginPath()
      ctx!.arc(0, -14, 14, 0, Math.PI * 2)
      ctx!.fill()
      ctx!.shadowBlur = 0
      ctx!.fillStyle = naPrimaria
      ctx!.beginPath(); ctx!.arc(-5, -17, 2.4, 0, Math.PI * 2); ctx!.arc(5, -17, 2.4, 0, Math.PI * 2); ctx!.fill()
      ctx!.restore()
    }

    escolher.current = (i: number) => {
      if (fase !== 'pergunta' && fase !== 'queda') return
      if (fase === 'queda') return
      if (pergunta.opcoes[i] === pergunta.resposta) {
        fase = 'pulo'; t = 0; destino = i
      } else {
        fase = 'erro'; t = 0; errada = i
        sequencia = 0
        progresso = 0
        setPlacar({ pontos, sequencia, recorde })
      }
    }

    let anterior = performance.now()
    const laco = (agora: number) => {
      const dt = Math.min(0.05, (agora - anterior) / 1000)
      anterior = agora
      t += dt
      if (fase === 'pergunta') {
        progresso += dt / limite
        if (progresso >= 1) {
          progresso = 1
          fase = 'queda'
          t = 0
          sequencia = 0
          recorde = Math.max(recorde, pontos)
          setPlacar({ pontos, sequencia, recorde })
        }
      }
      ctx.fillStyle = fundo
      ctx.fillRect(0, 0, L, A)
      for (const e of estrelas) {
        const y = ((e.y + camera * 0.3) % (A * 3)) - A
        ctx.fillStyle = secundario
        ctx.globalAlpha = 0.5
        ctx.beginPath(); ctx.arc(e.x, y, e.r, 0, Math.PI * 2); ctx.fill()
      }
      ctx.globalAlpha = 1

      let deslocamento = 0
      if (fase === 'pulo') {
        const p = Math.min(1, t / 0.55)
        deslocamento = p > 0.6 ? ((p - 0.6) / 0.4) * salto : 0
      }
      const yBase = baseY + deslocamento
      const yCima = baseY - salto + deslocamento
      nuvem(colunas[atual], yBase + 18, 90, 0.9, false)
      pergunta.opcoes.forEach((valor, i) => {
        const some = fase === 'erro' && i === errada ? Math.max(0, 1 - t / 0.7) : 1
        const deslizando = fase === 'erro' && i === errada ? t * 30 : 0
        const flutua = Math.sin(agora / 600 + i * 2) * 4
        nuvem(colunas[i], yCima + 18 + flutua + deslizando, 96, 0.92 * some, false)
        ctx.globalAlpha = some
        ctx.fillStyle = fase === 'erro' && i === errada ? perigo : fundo
        ctx.font = '600 22px Figtree, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(String(valor), colunas[i], yCima + 20 + flutua + deslizando)
        ctx.font = '500 12px Figtree, sans-serif'
        ctx.fillStyle = secundario
        ctx.fillText(String(i + 1), colunas[i], yCima + 56 + flutua + deslizando)
        ctx.globalAlpha = 1
      })

      if (fase === 'pulo') {
        const p = Math.min(1, t / 0.55)
        const x = colunas[atual] + (colunas[destino] - colunas[atual]) * p
        const y = baseY + (-salto) * p - Math.sin(Math.PI * p) * 70 + deslocamento
        heroi(x, y, Math.sin(Math.PI * p))
        if (t >= 0.8) {
          for (let k = 0; k < 18; k++) particulas.push({ x: colunas[destino], y: baseY, vx: (Math.random() - 0.5) * 220, vy: -Math.random() * 200, vida: 1 })
          atual = destino
          camera += salto
          pontos += 1
          sequencia += 1
          recorde = Math.max(recorde, pontos)
          nivel = Math.floor(pontos / 4)
          pergunta = novaPergunta(nivel)
          fase = 'pergunta'
          t = 0
          progresso = 0
          limite = limitePara(pontos)
          setPlacar({ pontos, sequencia, recorde })
        }
      } else if (fase === 'queda') {
        const quedaY = baseY + t * 160 + t * t * 900
        const some = Math.max(0, 1 - t / 1.1)
        ctx.save()
        ctx.globalAlpha = some
        heroi(colunas[atual], quedaY, 0)
        ctx.restore()
        nuvem(colunas[atual], yBase + 18, 90, 0.9 * some, false)
        if (t >= 1.1) {
          pergunta = novaPergunta(nivel)
          fase = 'pergunta'
          t = 0
          progresso = 0
          limite = limitePara(pontos)
          errada = -1
        }
      } else {
        const tremor = fase === 'erro' ? Math.sin(t * 50) * 6 * Math.max(0, 1 - t / 0.5) : 0
        const pulinho = fase === 'pergunta' ? Math.abs(Math.sin(agora / 350)) * 4 : 0
        heroi(colunas[atual] + tremor, baseY - pulinho, 0)
        if (fase === 'erro' && t > 0.9) { fase = 'pergunta'; t = 0; errada = -1; progresso = 0 }
      }

      for (let k = particulas.length - 1; k >= 0; k--) {
        const q = particulas[k]
        q.vy += 400 * dt; q.x += q.vx * dt; q.y += q.vy * dt; q.vida -= dt * 1.4
        if (q.vida <= 0) { particulas.splice(k, 1); continue }
        ctx.globalAlpha = q.vida
        ctx.fillStyle = primaria
        ctx.beginPath(); ctx.arc(q.x, q.y, 2.5, 0, Math.PI * 2); ctx.fill()
      }
      ctx.globalAlpha = 1

      ctx.fillStyle = textoCor
      ctx.font = '600 28px Figtree, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(`${pergunta.texto} = ?`, L / 2, 30)
      if (fase === 'pergunta' || fase === 'queda') {
        const barraL = Math.min(260, L * 0.6)
        const restante = Math.max(0, 1 - progresso)
        ctx.fillStyle = fase === 'queda' ? perigo : (restante < 0.3 ? perigo : primaria)
        ctx.beginPath()
        const yBarra = 52
        if (typeof ctx.roundRect === 'function') { ctx.roundRect(L / 2 - barraL / 2, yBarra, barraL, 6, 3) }
        else { ctx.rect(L / 2 - barraL / 2, yBarra, barraL, 6) }
        ctx.fill()
        ctx.save()
        ctx.beginPath()
        if (typeof ctx.roundRect === 'function') { ctx.roundRect(L / 2 - barraL / 2, yBarra, Math.max(0, barraL * restante), 6, 3) }
        else { ctx.rect(L / 2 - barraL / 2, yBarra, Math.max(0, barraL * restante), 6) }
        ctx.clip()
        ctx.fillStyle = fundo
        ctx.fillRect(L / 2 - barraL / 2, yBarra, barraL, 6)
        ctx.restore()
        if (fase === 'queda') {
          ctx.fillStyle = perigo
          ctx.font = '600 13px Figtree, sans-serif'
          ctx.fillText('Tempo esgotado — você caiu!', L / 2, 72)
        }
      }
      pedido = requestAnimationFrame(laco)
    }
    let pedido = requestAnimationFrame(laco)

    const clique = (e: MouseEvent) => {
      const r = canvas.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      if (y > baseY - 30) return
      const i = colunas.reduce((melhor, cx, k) => (Math.abs(cx - x) < Math.abs(colunas[melhor] - x) ? k : melhor), 0)
      escolher.current(i)
    }
    const tecla = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement | null
      if (alvo && ['INPUT', 'TEXTAREA'].includes(alvo.tagName)) return
      const mapa: Record<string, number> = { '1': 0, '2': 1, '3': 2, ArrowLeft: 0, ArrowUp: 1, ArrowRight: 2 }
      if (e.key in mapa) { e.preventDefault(); escolher.current(mapa[e.key]) }
    }
    canvas.addEventListener('click', clique)
    window.addEventListener('keydown', tecla)
    return () => {
      cancelAnimationFrame(pedido)
      canvas.removeEventListener('click', clique)
      window.removeEventListener('keydown', tecla)
    }
  }, [])

  return (
    <>
      <canvas ref={tela} className="w-full h-96 md:h-[32rem] block cursor-pointer" />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Acerte a conta antes que o tempo acabe ou você cai da nuvem. Clique na nuvem ou use 1, 2, 3 (ou as setas).</span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>
          {placar.pontos} nuvens · sequência {placar.sequencia} · recorde {placar.recorde}
        </span>
      </div>
    </>
  )
}
