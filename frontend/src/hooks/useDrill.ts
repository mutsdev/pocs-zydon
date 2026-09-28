import { useState, useEffect, useRef, useCallback } from 'react';

// ── Types ─────────────────────────────────────────────────────

interface DrillDimension {
  /** Identificador único da dimensão */
  key: string;
  /** Label exibido no context menu e breadcrumb */
  label: string;
  /** Descrição exibida no context menu */
  description?: string;
  /**
   * Query string passada ao queryFn.
   * Placeholders :PARAM são substituídos pelos accParams acumulados.
   * Ex: "12|vendedor=:vendedor|categoria=:categoria"
   */
  query: string;
  /**
   * filterKey: quando o usuário está NESTA dimensão (ela é o agrupamento ativo)
   * e clica num item, o name do item é adicionado ao accParams com esta chave.
   * Ex: dimensão "categoria" → filterKey: "categoria" → accParams.categoria = "Hardware"
   */
  filterKey: string;
  /** xKey dos dados retornados (default: 'name') */
  xKey?: string;
}

interface DrillLevel {
  dimension: DrillDimension;
  /** Valor clicado que originou este nível */
  clickedValue: string;
  /** Label para breadcrumb */
  label: string;
  /** Dados do nível ANTERIOR (para voltar via breadcrumb) */
  parentData: any[];
  /** xKey do nível ANTERIOR */
  parentXKey: string;
  /** Dados RESULTADO desta query (para restaurar ao navegar) */
  resultData: any[];
  /** xKey do resultado */
  resultXKey: string;
  /** Parâmetros acumulados de todos os níveis até este (inclusive) */
  accParams: Record<string, string>;
}

interface ContextMenuState {
  x: number;
  y: number;
  dimensions: DrillDimension[];
  onSelect: (dimensionKey: string) => void;
  onClose: () => void;
}

interface UseDrillOptions {
  /** Dados do nível raiz */
  rootData: any[];
  /** Dimensões disponíveis para drill-down (ordem livre — context menu mostra todas não usadas) */
  dimensions: DrillDimension[];
  /**
   * Função que executa a query e retorna rows.
   * Recebe a query string com :PARAM já substituídos.
   */
  queryFn: (query: string) => Promise<{ rows: any[] }>;
  /** xKey dos dados raiz (default: 'name') */
  xKey?: string;
  /**
   * filterKey do nível raiz. Quando o usuário clica num item na raiz,
   * o name do item é adicionado ao accParams com esta chave.
   * Ex: ranking de vendedores → rootFilterKey: 'vendedor'
   */
  rootFilterKey?: string;
  /** Label do nível raiz no breadcrumb (default: 'Visão Geral') */
  rootLabel?: string;
  /** Callback quando o nível de drill muda */
  onDrillChange?: (stack: DrillLevel[]) => void;
  /** Indica que o chart tem highlight ativo — drill vai pro botão direito em TODOS os níveis */
  hasHighlight?: boolean;
}

interface UseDrillReturn {
  /** Dados do nível atual (raiz ou drilled) */
  data: any[];
  /** xKey do nível atual */
  xKey: string;
  /** Profundidade atual (0 = raiz) */
  depth: number;
  /** Stack de níveis para breadcrumb */
  breadcrumbs: DrillLevel[];
  /** Click handler — abre context menu */
  handleClick: (item: any, index: number, event: any) => void;
  /** Right-click handler — abre context menu */
  handleRightClick: (item: any, index: number, event: any) => void;
  /** Navegar via breadcrumb (-1 = raiz, 0+ = nível específico) */
  navigateTo: (index: number) => void;
  /** Se está carregando dados do drill */
  loading: boolean;
  /** Props do context menu (null se fechado) */
  contextMenu: ContextMenuState | null;
  /** Título dinâmico (label do drill ou undefined para raiz) */
  drillTitle: string | undefined;
  /** Label do nível raiz */
  rootLabel: string;
  /** Se highlight está habilitado (hasHighlight && depth === 0) */
  isHighlightEnabled: boolean;
  /** Se o drill usa botão direito (true quando hasHighlight — mantém direito em TODOS os níveis) */
  usesRightClick: boolean;
  /** Props prontas para DrillBreadcrumb */
  breadcrumbProps: {
    stack: DrillLevel[];
    rootLabel: string;
    onNavigate: (index: number) => void;
  };
}

/**
 * useDrill — gerencia navegação drill-down LIVRE em gráficos.
 *
 * "Livre" = em qualquer nível, o context menu mostra TODAS as dimensões
 * que ainda não foram usadas. O usuário escolhe a ordem.
 *
 * Ao clicar num item, o name do item vira filtro (accParams[filterKey do nível atual]).
 * Ao escolher uma dimensão no menu, a SF dessa dimensão é chamada com todos os filtros acumulados.
 *
 * @example
 * const drill = useDrill({
 *   rootData: vendedores,
 *   rootFilterKey: 'vendedor',
 *   dimensions: [
 *     { key: 'categoria', label: 'Categorias', filterKey: 'categoria', query: '12|vendedor=:vendedor|categoria=:categoria|produto=:produto' },
 *     { key: 'produto', label: 'Produtos', filterKey: 'produto', query: '13|vendedor=:vendedor|categoria=:categoria|produto=:produto' },
 *   ],
 *   queryFn: async (q) => { ... },
 *   hasHighlight: true,
 * });
 */
export function useDrill({
  rootData,
  dimensions,
  queryFn,
  xKey: rootXKey = 'name',
  rootFilterKey,
  rootLabel = 'Visão Geral',
  onDrillChange,
  hasHighlight = false,
}: UseDrillOptions): UseDrillReturn {
  const [drillStack, setDrillStack] = useState<DrillLevel[]>([]);
  const [currentData, setCurrentData] = useState<any[]>(rootData);
  const [currentXKey, setCurrentXKey] = useState<string>(rootXKey);
  const [loading, setLoading] = useState(false);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    item: any;
    index: number;
  } | null>(null);

  const onDrillChangeRef = useRef(onDrillChange);
  onDrillChangeRef.current = onDrillChange;

  // Sync rootData changes (when at root level)
  useEffect(() => {
    if (drillStack.length === 0) {
      setCurrentData(rootData);
    }
  }, [rootData, drillStack.length]);

  // Available dimensions (exclude already used in stack)
  const usedKeys = new Set(drillStack.map(s => s.dimension.key));
  const availableDimensions = dimensions.filter(d => !usedKeys.has(d.key));

  // Highlight enabled: hasHighlight && at root level
  const isHighlightEnabled = hasHighlight && drillStack.length === 0;

  // Open context menu at given coordinates
  const openContextMenu = useCallback((item: any, index: number, cx: number, cy: number) => {
    setContextMenu({ x: cx, y: cy, item, index });
  }, []);

  // Click handler
  const handleClick = useCallback((item: any, index: number, event: any) => {
    const cx = event?.clientX ?? event?.nativeEvent?.clientX ?? 200;
    const cy = event?.clientY ?? event?.nativeEvent?.clientY ?? 200;
    openContextMenu(item, index, cx, cy);
  }, [openContextMenu]);

  // Right-click handler
  const handleRightClick = useCallback((item: any, index: number, event: any) => {
    const cx = event?.clientX ?? event?.nativeEvent?.clientX ?? 200;
    const cy = event?.clientY ?? event?.nativeEvent?.clientY ?? 200;
    openContextMenu(item, index, cx, cy);
  }, [openContextMenu]);

  /**
   * Descobre qual filterKey corresponde ao nível ATUAL (de onde o item foi clicado).
   * - depth 0 → rootFilterKey
   * - depth N → filterKey da última dimensão no stack
   */
  const getCurrentFilterKey = useCallback((): string | undefined => {
    if (drillStack.length === 0) return rootFilterKey;
    return drillStack[drillStack.length - 1].dimension.filterKey;
  }, [drillStack, rootFilterKey]);

  // Dimension selected from context menu
  const handleSelectDimension = useCallback(async (dimensionKey: string) => {
    if (!contextMenu) return;
    const dimension = dimensions.find(d => d.key === dimensionKey);
    if (!dimension) return;

    const clickedItem = contextMenu.item;
    const clickedName = String(clickedItem.name ?? clickedItem.label ?? '');
    setContextMenu(null);
    setLoading(true);

    try {
      // Get accumulated params from previous levels
      const prevAcc = drillStack.length > 0
        ? { ...drillStack[drillStack.length - 1].accParams }
        : {};

      // Add the clicked item as a filter using the CURRENT level's filterKey
      const currentFK = getCurrentFilterKey();
      if (currentFK && clickedName) {
        prevAcc[currentFK] = clickedName;
      }

      const accParams = { ...prevAcc };

      // Build query: replace :PARAM with accumulated values, unused params → ''
      let query = dimension.query;
      Object.entries(accParams).forEach(([param, value]) => {
        query = query.replace(new RegExp(`:${param}`, 'g'), value);
      });
      // Any remaining :PARAM that wasn't in accParams → replace with empty
      query = query.replace(/:[a-zA-Z_]+/g, '');

      const result = await queryFn(query);
      const rows = result.rows || [];
      const resultXKey = dimension.xKey || 'name';

      const levelLabel = `${clickedName} › ${dimension.label}`;

      const newLevel: DrillLevel = {
        dimension,
        clickedValue: clickedName,
        label: levelLabel,
        parentData: currentData,
        parentXKey: currentXKey,
        resultData: rows,
        resultXKey,
        accParams,
      };

      const newStack = [...drillStack, newLevel];
      setDrillStack(newStack);
      setCurrentData(rows);
      setCurrentXKey(resultXKey);
      onDrillChangeRef.current?.(newStack);
    } catch (err) {
      console.error('[useDrill] Query error:', err);
    } finally {
      setLoading(false);
    }
  }, [contextMenu, dimensions, currentData, currentXKey, drillStack, queryFn, getCurrentFilterKey]);

  // Navigate via breadcrumb
  const navigateTo = useCallback((index: number) => {
    setContextMenu(null);
    if (index < 0) {
      // Go to root
      setCurrentData(rootData);
      setCurrentXKey(rootXKey);
      setDrillStack([]);
      onDrillChangeRef.current?.([]);
    } else {
      // Go to specific level — show the RESULT of that level
      const targetLevel = drillStack[index];
      const newStack = drillStack.slice(0, index + 1); // keep up to and including index
      setDrillStack(newStack);
      setCurrentData(targetLevel.resultData);
      setCurrentXKey(targetLevel.resultXKey);
      onDrillChangeRef.current?.(newStack);
    }
  }, [rootData, rootXKey, drillStack]);

  // Close context menu
  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  // Dynamic title
  const drillTitle = drillStack.length > 0
    ? drillStack[drillStack.length - 1].label
    : undefined;

  // Context menu props (null if closed)
  const contextMenuProps: ContextMenuState | null = contextMenu
    ? {
        x: contextMenu.x,
        y: contextMenu.y,
        dimensions: availableDimensions,
        onSelect: handleSelectDimension,
        onClose: closeContextMenu,
      }
    : null;

  // Breadcrumb props
  const breadcrumbProps = {
    stack: drillStack,
    rootLabel,
    onNavigate: navigateTo,
  };

  return {
    data: currentData,
    xKey: currentXKey,
    depth: drillStack.length,
    breadcrumbs: drillStack,
    handleClick,
    handleRightClick,
    navigateTo,
    loading,
    contextMenu: contextMenuProps,
    drillTitle,
    rootLabel,
    isHighlightEnabled,
    usesRightClick: hasHighlight,
    breadcrumbProps,
  };
}
