export const SF = {
  anexo_parte: '5fd9c4d2-60a1-4c64-8c24-ca1b57d29cca',
  curadoria_salvar: '61451fd2-3b69-4f59-bc82-44d54c79e773',
  executivo_ativo: 'b4c68cd0-872b-475c-bc5f-3f9b4bc3e099',
  executivo_entrar: '882ce495-7bf1-4bf1-b422-c9ac3e4f6e6a',
  executivo_salvar: 'd42bc07d-3506-49d9-9376-1220825e332a',
  executivos_listar: 'd8669dab-6cca-4a6f-9e86-d0ce74dcd20c',
  logo_parte: '3d87d565-f988-4724-8f2a-3ef89c44fe3c',
  pedido_abrir: '2958f983-0c43-4088-8423-ee45e3dce08c',
  pedido_acao: '30e3d129-e9c3-4e1a-ba3c-ef715ae8edcb',
  pedido_eventos: '09b33f93-24f3-4886-a981-39d563ad43ee',
  pedido_excluir: '4923e2fd-136e-4b63-8b63-9b8d8dddaa75',
  pedido_ler: '8bbd20ec-6cab-4df9-b435-41ee125d6794',
  pedido_pecas: 'cc655493-6be9-4aeb-9a88-c760182f5c9a',
  pedidos_listar: '82a7ceb8-6096-4f2c-be44-e1bf8f7fce3f',
  relatorio_pocs: '1f40e96c-252d-48cc-8e30-bedc3569ab56',
  segmentos_listar: '24f264c9-8bbe-4f0b-bb03-b2b7941e6895',
  sessao: 'b728c777-ac78-463f-96fa-264b97d12018',
} as const

export type SfNome = keyof typeof SF
