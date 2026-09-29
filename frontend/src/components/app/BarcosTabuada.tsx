import { useEffect, useRef, useState } from 'react'
import { Volume2, VolumeX } from 'lucide-react'

function cor(nome: string, reserva: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(nome).trim() || reserva
}

function sortear(min: number, max: number) {
  return min + Math.floor(Math.random() * (max - min + 1))
}

interface Pergunta { texto: string; resposta: number; opcoes: number[] }

function novaPergunta(nivel: number): Pergunta {
  const tetoTabela = Math.min(12, 5 + nivel)
  const a = sortear(2, tetoTabela)
  const b = sortear(2, nivel < 2 ? 10 : 12)
  const resposta = a * b
  const opcoes = new Set<number>([resposta])
  const vizinhos = [a * (b + 1), a * (b - 1), (a + 1) * b, (a - 1) * b, resposta + 10, resposta - 10, resposta + 2, resposta - 2]
  while (opcoes.size < 3) {
    const candidato = Math.random() < 0.75 ? vizinhos[sortear(0, vizinhos.length - 1)] : resposta + sortear(-6, 6)
    if (candidato > 0) opcoes.add(candidato)
  }
  return { texto: `${a} × ${b}`, resposta, opcoes: [...opcoes].sort(() => Math.random() - 0.5) }
}

type Fase = 'inicio' | 'jogando' | 'pulo' | 'rolagem' | 'fim'
const CHAVE_RECORDE = 'barcos-tabuada-recorde'
const CHAVE_SOM = 'barcos-som-mudo'

function lerMudo() {
  try { return localStorage.getItem(CHAVE_SOM) === '1' } catch { return false }
}

interface Som { ativar: () => void; mar: (vel: number) => void; tensao: (progresso: number, jogando: boolean) => void; mordida: () => void; derrota: () => void; mudar: (mudo: boolean) => void; fechar: () => void }

function criarSom(mudoInicial: boolean): Som {
  let audio: AudioContext | null = null
  let mestre: GainNode | null = null
  let ruido: AudioBuffer | null = null
  let marGanho: GainNode | null = null
  let marFiltro: BiquadFilterNode | null = null
  let tensaoGanho: GainNode | null = null
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
    const fonteMar = audio.createBufferSource()
    fonteMar.buffer = ruido
    fonteMar.loop = true
    fonteMar.playbackRate.value = 0.5
    marFiltro = audio.createBiquadFilter()
    marFiltro.type = 'lowpass'
    marFiltro.frequency.value = 500
    marGanho = audio.createGain()
    marGanho.gain.value = 0
    fonteMar.connect(marFiltro).connect(marGanho).connect(mestre)
    fonteMar.start()
    const onda = audio.createOscillator()
    onda.type = 'sine'
    onda.frequency.value = 0.13
    const ondaGanho = audio.createGain()
    ondaGanho.gain.value = 0.03
    onda.connect(ondaGanho).connect(marGanho.gain)
    onda.start()
    const oscA = audio.createOscillator()
    oscA.type = 'sine'
    oscA.frequency.value = 55
    const oscB = audio.createOscillator()
    oscB.type = 'sine'
    oscB.frequency.value = 58.27
    tensaoGanho = audio.createGain()
    tensaoGanho.gain.value = 0
    oscA.connect(tensaoGanho)
    oscB.connect(tensaoGanho)
    tensaoGanho.connect(mestre)
    oscA.start()
    oscB.start()
  }

  const mar = (vel: number) => {
    if (!audio || !marGanho || !marFiltro) return
    const forca = Math.min(1, Math.max(0, (vel - 0.5) / 3.5))
    const agora = audio.currentTime
    marGanho.gain.setTargetAtTime(0.09 + forca * 0.16, agora, 0.4)
    marFiltro.frequency.setTargetAtTime(380 + forca * 750, agora, 0.4)
  }

  const tensao = (progresso: number, jogando: boolean) => {
    if (!audio || !tensaoGanho) return
    const alvo = jogando ? progresso * progresso * 0.4 : 0
    tensaoGanho.gain.setTargetAtTime(alvo, audio.currentTime, 0.12)
  }

  const croc = (quando: number, grave: number) => {
    if (!audio || !mestre || !ruido) return
    const t0 = quando
    const estalo = audio.createBufferSource()
    estalo.buffer = ruido
    const f = audio.createBiquadFilter()
    f.type = 'lowpass'
    f.frequency.value = 900
    const g = audio.createGain()
    g.gain.setValueAtTime(0.7, t0)
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.14)
    estalo.connect(f).connect(g).connect(mestre)
    estalo.start(t0, Math.random())
    estalo.stop(t0 + 0.16)
    const baque = audio.createOscillator()
    baque.type = 'sine'
    baque.frequency.setValueAtTime(grave, t0)
    baque.frequency.exponentialRampToValueAtTime(55, t0 + 0.16)
    const bg = audio.createGain()
    bg.gain.setValueAtTime(0.55, t0)
    bg.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.2)
    baque.connect(bg).connect(mestre)
    baque.start(t0)
    baque.stop(t0 + 0.22)
  }

  const mordida = () => {
    if (!audio) return
    const agora = audio.currentTime
    croc(agora, 260)
    croc(agora + 0.14, 200)
  }

  const derrota = () => {
    if (!audio || !mestre) return
    const notas = [392, 311.13, 233.08, 155.56]
    notas.forEach((freq, i) => {
      const t0 = audio!.currentTime + i * 0.22
      const osc = audio!.createOscillator()
      osc.type = 'triangle'
      osc.frequency.value = freq
      const g = audio!.createGain()
      g.gain.setValueAtTime(0.0001, t0)
      g.gain.exponentialRampToValueAtTime(0.3, t0 + 0.03)
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.24)
      osc.connect(g).connect(mestre!)
      osc.start(t0)
      osc.stop(t0 + 0.26)
    })
  }

  const mudar = (valor: boolean) => {
    mudo = valor
    if (audio && mestre) mestre.gain.setTargetAtTime(valor ? 0 : 1, audio.currentTime, 0.03)
  }

  const fechar = () => { tensao(0, false); void audio?.close(); audio = null }

  return { ativar, mar, tensao, mordida, derrota, mudar, fechar }
}

function lerRecorde() {
  try { return Number(localStorage.getItem(CHAVE_RECORDE)) || 0 } catch { return 0 }
}

export default function BarcosTabuada() {
  const tela = useRef<HTMLCanvasElement>(null)
  const [placar, setPlacar] = useState({ pontos: 0, recorde: lerRecorde() })
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
    const naPrimaria = cor('--color-on-primary', '#19181a')
    const fundo = cor('--color-surface', '#fdfdfc')
    const textoCor = cor('--color-text', '#0d0f14')
    const secundario = cor('--color-text-secondary', '#5b6472')
    const agua = cor('--color-info', '#1f66c4')
    const perigo = cor('--color-danger', '#c62f2a')
    const sucesso = cor('--color-success', '#0f7a52')
    const borda = cor('--color-border', '#e3e6ec')

    const largBarco = Math.max(78, Math.min(128, L * 0.2))
    const altCasco = 22
    const xAtual = Math.max(largBarco * 0.9, L * 0.3)
    const xOpcoes = Math.min(L - largBarco * 0.62, L * 0.76)
    const faixas = [A * 0.36, A * 0.58, A * 0.8]
    const yAtual = faixas[1]

    let fase: Fase = 'inicio'
    let t = 0
    let pontos = 0
    let recorde = lerRecorde()
    let pergunta = novaPergunta(0)
    let progresso = 0
    let limite = 9
    let destino = -1
    let afundando: number[] = []
    let tempoAfundar: Record<number, number> = {}
    let tubaraoX = xAtual - largBarco / 2 - 40
    let deslocamentoOnda = 0
    let aviso = ''
    let tempoAviso = 0
    let particulas: { x: number; y: number; vx: number; vy: number; vida: number; cor: string }[] = []
    let velho: { x: number; y: number; comido: number } | null = null

    const limitePara = (n: number) => Math.max(2.8, 9 * Math.pow(0.93, n))
    const velocidade = () => (fase === 'inicio' || fase === 'fim' ? 0.5 : 1 + pontos * 0.15)
    let espumas = Array.from({ length: 34 }, () => ({ x: Math.random() * L, y: A * 0.24 + Math.random() * A * 0.74, tam: 6 + Math.random() * 18 }))

    function comecar() {
      fase = 'jogando'
      t = 0
      pontos = 0
      progresso = 0
      pergunta = novaPergunta(0)
      limite = limitePara(0)
      afundando = []
      tempoAfundar = {}
      velho = null
      tubaraoX = xAtual - largBarco / 2 - 60
      setPlacar({ pontos: 0, recorde })
    }

    function escolher(i: number) {
      if (fase === 'inicio' || fase === 'fim') { comecar(); return }
      if (fase !== 'jogando' || afundando.includes(i)) return
      if (pergunta.opcoes[i] === pergunta.resposta) {
        fase = 'pulo'
        destino = i
        t = 0
      } else {
        afundando.push(i)
        som.current?.mordida()
        tempoAfundar[i] = 0
        progresso = Math.min(0.97, progresso + 0.18)
        aviso = `${pergunta.texto} não é ${pergunta.opcoes[i]}`
        tempoAviso = 1.4
      }
    }

    function casco(x: number, y: number, comido: number, alfa: number, afundar: number) {
      const esquerda = x - largBarco / 2
      const corte = esquerda + comido * largBarco
      ctx!.save()
      ctx!.globalAlpha = alfa
      ctx!.translate(0, afundar * 40)
      ctx!.beginPath()
      ctx!.rect(corte, y - 90, largBarco + 20, 140)
      ctx!.clip()
      ctx!.fillStyle = textoCor
      ctx!.fillRect(x - 1.5, y - 58, 3, 58)
      ctx!.fillStyle = borda
      ctx!.beginPath()
      ctx!.moveTo(x + 3, y - 56)
      ctx!.lineTo(x + largBarco * 0.36, y - 10)
      ctx!.lineTo(x + 3, y - 10)
      ctx!.closePath()
      ctx!.fill()
      ctx!.fillStyle = secundario
      ctx!.beginPath()
      ctx!.moveTo(esquerda, y)
      ctx!.lineTo(esquerda + largBarco, y)
      ctx!.lineTo(esquerda + largBarco * 0.86, y + altCasco)
      ctx!.lineTo(esquerda + largBarco * 0.14, y + altCasco)
      ctx!.closePath()
      ctx!.fill()
      ctx!.restore()
      if (comido > 0.01) {
        ctx!.save()
        ctx!.globalAlpha = alfa
        ctx!.fillStyle = fundo
        ctx!.beginPath()
        ctx!.moveTo(corte, y - 2)
        for (let k = 0; k <= 6; k++) ctx!.lineTo(corte + (k % 2 === 0 ? 0 : 7), y + (k * altCasco) / 6)
        ctx!.lineTo(corte - 2, y + altCasco + 2)
        ctx!.lineTo(corte - 2, y - 2)
        ctx!.closePath()
        ctx!.fill()
        ctx!.restore()
      }
    }

    function rotulo(x: number, y: number, valor: number, tecla: number, alfa: number, afundar: number, errado: boolean) {
      ctx!.save()
      ctx!.globalAlpha = alfa
      ctx!.translate(0, afundar * 40)
      ctx!.fillStyle = errado ? perigo : fundo
      ctx!.font = '700 18px Figtree, sans-serif'
      ctx!.textAlign = 'center'
      ctx!.textBaseline = 'middle'
      ctx!.fillText(String(valor), x, y + altCasco / 2 + 1)
      ctx!.fillStyle = secundario
      ctx!.font = '500 12px Figtree, sans-serif'
      ctx!.fillText(`tecla ${tecla}`, x - largBarco * 0.22, y - 30)
      ctx!.restore()
    }

    function marinheiro(x: number, y: number, esticado: number) {
      ctx!.fillStyle = primaria
      ctx!.strokeStyle = naPrimaria
      ctx!.lineWidth = 2
      ctx!.beginPath()
      ctx!.roundRect(x - 9, y - 30 - esticado * 4, 18, 24 + esticado * 4, 6)
      ctx!.fill()
      ctx!.stroke()
      ctx!.beginPath()
      ctx!.arc(x, y - 40 - esticado * 4, 8, 0, Math.PI * 2)
      ctx!.fill()
      ctx!.stroke()
      ctx!.fillStyle = naPrimaria
      ctx!.beginPath(); ctx!.arc(x + 3, y - 41 - esticado * 4, 1.6, 0, Math.PI * 2); ctx!.fill()
    }

    function tubarao(x: number, y: number, boca: number) {
      ctx!.save()
      ctx!.fillStyle = perigo
      ctx!.beginPath()
      ctx!.moveTo(x - 150, y + 30)
      ctx!.quadraticCurveTo(x - 90, y - 40, x - 10, y - 10 - boca * 10)
      ctx!.lineTo(x + 8, y + 6)
      ctx!.lineTo(x - 10, y + 22 + boca * 10)
      ctx!.quadraticCurveTo(x - 80, y + 50, x - 150, y + 30)
      ctx!.fill()
      ctx!.beginPath()
      ctx!.moveTo(x - 95, y - 18)
      ctx!.lineTo(x - 80, y - 55)
      ctx!.lineTo(x - 60, y - 20)
      ctx!.fill()
      ctx!.fillStyle = fundo
      for (let k = 0; k < 4; k++) {
        const bx = x - 34 + k * 9
        ctx!.beginPath(); ctx!.moveTo(bx, y - 6 - boca * 6); ctx!.lineTo(bx + 4, y + 2); ctx!.lineTo(bx + 8, y - 6 - boca * 6); ctx!.fill()
        ctx!.beginPath(); ctx!.moveTo(bx, y + 18 + boca * 6); ctx!.lineTo(bx + 4, y + 10); ctx!.lineTo(bx + 8, y + 18 + boca * 6); ctx!.fill()
      }
      ctx!.beginPath(); ctx!.arc(x - 44, y - 16, 4, 0, Math.PI * 2); ctx!.fill()
      ctx!.fillStyle = textoCor
      ctx!.beginPath(); ctx!.arc(x - 43, y - 16, 2, 0, Math.PI * 2); ctx!.fill()
      ctx!.restore()
    }

    function ondas(tempo: number) {
      ctx!.save()
      ctx!.strokeStyle = agua
      ctx!.lineWidth = 2
      for (let f = 0; f < 5; f++) {
        const y = A * 0.26 + f * (A * 0.17)
        ctx!.globalAlpha = 0.14 + f * 0.04
        ctx!.beginPath()
        for (let x = 0; x <= L; x += 8) {
          const yy = y + Math.sin((x + deslocamentoOnda * (0.6 + f * 0.25) + f * 40) / 38 + tempo * 0.6) * 4
          if (x === 0) ctx!.moveTo(x, yy)
          else ctx!.lineTo(x, yy)
        }
        ctx!.stroke()
      }
      ctx!.restore()
    }

    function espuma(dt: number) {
      const vel = velocidade()
      ctx!.save()
      ctx!.strokeStyle = agua
      ctx!.lineCap = 'round'
      ctx!.lineWidth = 2
      for (const e of espumas) {
        const profundidade = 0.5 + (e.y / A) * 0.8
        e.x -= dt * 150 * vel * profundidade
        if (e.x < -e.tam) { e.x = L + Math.random() * 40; e.y = A * 0.24 + Math.random() * A * 0.74 }
        ctx!.globalAlpha = 0.18 + profundidade * 0.12
        ctx!.beginPath(); ctx!.moveTo(e.x, e.y); ctx!.lineTo(e.x + e.tam * (0.6 + vel * 0.25), e.y); ctx!.stroke()
      }
      ctx!.restore()
    }

    function esteira(x: number, y: number, alfa: number) {
      const vel = velocidade()
      ctx!.save()
      ctx!.strokeStyle = agua
      ctx!.lineCap = 'round'
      ctx!.lineWidth = 2
      for (let k = 0; k < 3; k++) {
        const fase0 = ((relogio * 2.2 * vel + k / 3) % 1)
        const xx = x - largBarco * 0.45 - fase0 * largBarco * (0.5 + vel * 0.2)
        ctx!.globalAlpha = alfa * (1 - fase0) * 0.55
        ctx!.beginPath()
        ctx!.moveTo(xx, y + altCasco - 2 - k * 5)
        ctx!.lineTo(xx - 14 - vel * 6, y + altCasco - 2 - k * 5 + (k - 1) * 3)
        ctx!.stroke()
      }
      ctx!.restore()
    }

    function explodir(x: number, y: number, c: string, n: number) {
      for (let k = 0; k < n; k++) particulas.push({ x, y, vx: (Math.random() - 0.5) * 260, vy: -Math.random() * 220, vida: 1, cor: c })
    }

    let anterior = performance.now()
    let relogio = 0
    let ultimoPlacar = -1
    const laco = (agora: number) => {
      const dt = Math.min(0.05, (agora - anterior) / 1000)
      anterior = agora
      relogio += dt
      t += dt
      deslocamentoOnda += dt * 90 * velocidade()
      som.current?.mar(velocidade())
      som.current?.tensao(fase === 'jogando' ? progresso : 0, fase === 'jogando')

      ctx.fillStyle = fundo
      ctx.fillRect(0, 0, L, A)
      ondas(relogio)
      espuma(dt)

      if (fase === 'jogando') {
        progresso += dt / limite
        if (progresso >= 1) {
          progresso = 1
          fase = 'fim'
          t = 0
          explodir(xAtual, yAtual, agua, 30)
          som.current?.mordida()
          window.setTimeout(() => som.current?.derrota(), 380)
          if (pontos > recorde) { recorde = pontos; try { localStorage.setItem(CHAVE_RECORDE, String(recorde)) } catch { /* sem armazenamento */ } }
          setPlacar({ pontos, recorde })
        }
      }
      for (const i of afundando) tempoAfundar[i] = (tempoAfundar[i] || 0) + dt

      const balanco = (k: number) => Math.sin(relogio * 2 + k * 1.7) * 3
      const alvoTubarao = xAtual - largBarco / 2 + (fase === 'inicio' ? -0.35 : progresso) * largBarco
      tubaraoX += (alvoTubarao - tubaraoX) * Math.min(1, dt * 6)

      let xNovo = xOpcoes
      let yNovo = destino >= 0 ? faixas[destino] : yAtual
      const pr = fase === 'rolagem' ? Math.min(1, t / 0.45) : 0
      const suave = pr * pr * (3 - 2 * pr)

      if (velho) {
        velho.x -= dt * 260 * velocidade()
        velho.comido = Math.min(1, velho.comido + dt * 2)
        casco(velho.x, velho.y + balanco(9), velho.comido, Math.max(0, 1 - velho.comido), velho.comido)
        if (velho.comido >= 1) velho = null
      }

      if (fase !== 'rolagem' && fase !== 'fim') {
        esteira(xAtual, yAtual + balanco(0), 1)
        casco(xAtual, yAtual + balanco(0), fase === 'inicio' ? 0 : progresso, 1, 0)
      } else if (fase === 'fim') {
        casco(xAtual, yAtual + balanco(0), 1, Math.max(0, 1 - t), Math.min(1, t))
      }

      if (fase !== 'fim') {
        pergunta.opcoes.forEach((valor, i) => {
          const a = tempoAfundar[i] ?? 0
          const afundar = afundando.includes(i) ? Math.min(1, a / 0.8) : 0
          let x = xOpcoes
          let y = faixas[i]
          let alfa = 1 - afundar
          if (fase === 'rolagem') {
            if (i === destino) {
              x = xOpcoes + (xAtual - xOpcoes) * suave
              y = faixas[i] + (yAtual - faixas[i]) * suave
              xNovo = x
              yNovo = y
            } else alfa *= 1 - suave
          }
          const entrada = fase === 'jogando' && t < 0.35 && pontos > 0 ? (1 - t / 0.35) * (L - xOpcoes + largBarco) : 0
          x += entrada
          if (alfa <= 0) return
          if (!afundar) esteira(x, y + balanco(i + 1), alfa)
          casco(x, y + balanco(i + 1), 0, alfa, afundar)
          if (!(fase === 'rolagem' && i === destino)) rotulo(x, y + balanco(i + 1), valor, i + 1, alfa, afundar, afundando.includes(i))
        })
      }

      if (fase === 'pulo') {
        const p = Math.min(1, t / 0.5)
        const x = xAtual + (xOpcoes - xAtual) * p
        const y = yAtual + (faixas[destino] - yAtual) * p - Math.sin(Math.PI * p) * 80
        marinheiro(x, y, Math.sin(Math.PI * p))
        if (p >= 1) {
          explodir(xOpcoes, faixas[destino], sucesso, 16)
          velho = { x: xAtual, y: yAtual, comido: progresso }
          fase = 'rolagem'
          t = 0
        }
      } else if (fase === 'rolagem') {
        marinheiro(xNovo, yNovo + balanco(destino + 1), 0)
        if (pr >= 1) {
          pontos += 1
          progresso = 0
          limite = limitePara(pontos)
          pergunta = novaPergunta(Math.floor(pontos / 4))
          afundando = []
          tempoAfundar = {}
          destino = -1
          fase = 'jogando'
          t = 0
          tubaraoX -= largBarco * 0.4
        }
      } else if (fase !== 'fim') {
        marinheiro(xAtual, yAtual + balanco(0) - Math.abs(Math.sin(relogio * 3)) * 2, 0)
      }

      tubarao(tubaraoX, yAtual + 4 + balanco(0) * 0.5, Math.abs(Math.sin(relogio * 7)))

      for (let k = particulas.length - 1; k >= 0; k--) {
        const q = particulas[k]
        q.vy += 420 * dt; q.x += q.vx * dt; q.y += q.vy * dt; q.vida -= dt * 1.3
        if (q.vida <= 0) { particulas.splice(k, 1); continue }
        ctx.globalAlpha = q.vida
        ctx.fillStyle = q.cor
        ctx.beginPath(); ctx.arc(q.x, q.y, 2.6, 0, Math.PI * 2); ctx.fill()
      }
      ctx.globalAlpha = 1

      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      if (fase === 'inicio' || fase === 'fim') {
        ctx.fillStyle = textoCor
        ctx.font = '600 24px Figtree, sans-serif'
        ctx.fillText(fase === 'inicio' ? 'Barcos da tabuada' : 'O tubarão comeu seu barco!', L / 2, 38)
        ctx.font = '400 14px Figtree, sans-serif'
        ctx.fillStyle = secundario
        ctx.fillText(fase === 'inicio'
          ? 'Clique ou aperte Enter para começar'
          : `Você pulou ${pontos} ${pontos === 1 ? 'barco' : 'barcos'} · clique ou Enter para jogar de novo`, L / 2, 66)
      } else {
        ctx.fillStyle = textoCor
        ctx.font = '700 30px Figtree, sans-serif'
        ctx.fillText(`${pergunta.texto} = ?`, L / 2, 34)
        const barraL = Math.min(260, L * 0.6)
        const restante = 1 - progresso
        ctx.fillStyle = borda
        ctx.beginPath(); ctx.roundRect(L / 2 - barraL / 2, 58, barraL, 6, 3); ctx.fill()
        ctx.fillStyle = restante < 0.3 ? perigo : primaria
        ctx.beginPath(); ctx.roundRect(L / 2 - barraL / 2, 58, Math.max(0, barraL * restante), 6, 3); ctx.fill()
        ctx.textAlign = 'left'
        ctx.fillStyle = secundario
        ctx.font = '500 12px Figtree, sans-serif'
        ctx.fillText(`velocidade ${velocidade().toFixed(2).replace('.', ',')}×`, 16, 20)
        ctx.textAlign = 'center'
        if (tempoAviso > 0) {
          tempoAviso -= dt
          ctx.globalAlpha = Math.min(1, tempoAviso * 2)
          ctx.fillStyle = perigo
          ctx.font = '600 14px Figtree, sans-serif'
          ctx.fillText(aviso, L / 2, 82)
          ctx.globalAlpha = 1
        }
      }

      if (pontos !== ultimoPlacar && fase === 'jogando') { ultimoPlacar = pontos; setPlacar({ pontos, recorde: Math.max(recorde, pontos) }) }
      pedido = requestAnimationFrame(laco)
    }
    let pedido = requestAnimationFrame(laco)

    const clique = (e: MouseEvent) => {
      som.current?.ativar()
      if (fase !== 'jogando') { escolher(0); return }
      const r = canvas.getBoundingClientRect()
      const x = e.clientX - r.left
      const y = e.clientY - r.top
      if (x < xOpcoes - largBarco * 0.8) return
      const i = faixas.reduce((melhor, fy, k) => (Math.abs(fy - y) < Math.abs(faixas[melhor] - y) ? k : melhor), 0)
      escolher(i)
    }
    const tecla = (e: KeyboardEvent) => {
      som.current?.ativar()
      const alvo = e.target as HTMLElement | null
      if (alvo && (['INPUT', 'TEXTAREA', 'SELECT'].includes(alvo.tagName) || alvo.isContentEditable)) return
      if ((e.key === 'Enter' || e.key === ' ') && (fase === 'inicio' || fase === 'fim')) { e.preventDefault(); comecar(); return }
      const mapa: Record<string, number> = { '1': 0, '2': 1, '3': 2, ArrowUp: 0, ArrowRight: 1, ArrowDown: 2 }
      if (e.key in mapa && fase === 'jogando') { e.preventDefault(); escolher(mapa[e.key]) }
    }
    canvas.addEventListener('click', clique)
    window.addEventListener('keydown', tecla)
    return () => {
      cancelAnimationFrame(pedido)
      som.current?.tensao(0, false)
      canvas.removeEventListener('click', clique)
      window.removeEventListener('keydown', tecla)
    }
  }, [])

  return (
    <>
      <canvas ref={tela} className="w-full h-96 md:h-[32rem] block cursor-pointer" />
      <div className="flex flex-wrap items-center gap-3 px-5 pb-5">
        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Resolva a conta de vezes e pule para o barco com a resposta antes que o tubarão coma o seu. Clique no barco ou use 1, 2, 3. A cada acerto o mar fica mais rápido e o tempo mais curto; errar dá vantagem ao tubarão.
        </span>
        <span className="ml-auto text-sm tabular-nums font-medium" style={{ color: 'var(--color-primary-text)' }}>
          {placar.pontos} barcos · recorde {placar.recorde}
        </span>
        <button
          onClick={alternarSom}
          aria-label={mudo ? 'Ligar o som' : 'Desligar o som'}
          title={mudo ? 'Ligar o som' : 'Desligar o som'}
          className="h-10 w-10 inline-flex items-center justify-center rounded-md cursor-pointer"
          style={{ backgroundColor: 'var(--color-primary-bg)', color: 'var(--color-primary-text)' }}
        >
          {mudo ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
      </div>
    </>
  )
}
