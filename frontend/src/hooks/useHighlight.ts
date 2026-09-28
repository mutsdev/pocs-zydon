import { useState, useCallback } from 'react';

/**
 * useHighlight — gerencia seleção de índices em gráficos.
 *
 * Regras:
 * - Click normal: limpa tudo e seleciona só o clicado.
 *   Se o clicado já era o único selecionado, limpa tudo (toggle off).
 * - Shift+Click: toggle individual sem afetar os demais.
 *
 * Retorna props prontas para qualquer chart:
 *   activeIndex → passar como prop `activeIndex` do chart
 *   handler     → passar como `onBarClick`, `onDotClick`, ou `onSliceClick`
 *   clear       → limpar seleção
 *   selected    → array de índices selecionados (para uso externo, ex: filtrar tabela)
 *
 * @example
 * const hl = useHighlight();
 * <ShadcnBarChart activeIndex={hl.activeIndex} onBarClick={hl.handler} />
 * <ShadcnLineChart activeIndex={hl.activeIndex} onDotClick={hl.handler} />
 * <ShadcnPieChart activeIndex={hl.activeIndex} onSliceClick={hl.handler} />
 */
export function useHighlight() {
  const [selected, setSelected] = useState<number[]>([]);

  const handler = useCallback((_item: any, index: number, event: any) => {
    // Extract shiftKey from any event shape Recharts may pass
    const shift = !!(
      event?.shiftKey
      || event?.nativeEvent?.shiftKey
      || (typeof event === 'object' && event !== null && 'shiftKey' in event && event.shiftKey)
    );

    if (shift) {
      // Shift+Click: toggle individual sem afetar os demais
      setSelected(prev =>
        prev.includes(index)
          ? prev.filter(i => i !== index)
          : [...prev, index]
      );
    } else {
      // Click normal: limpa tudo e ativa só este.
      // Se já era o único selecionado, limpa (toggle off).
      setSelected(prev =>
        prev.length === 1 && prev[0] === index ? [] : [index]
      );
    }
  }, []);

  const clear = useCallback(() => setSelected([]), []);

  // activeIndex: undefined means "no filter" → chart renders all at full opacity
  const activeIndex = selected.length > 0 ? selected : undefined;

  return { selected, setSelected, handler, clear, activeIndex };
}
