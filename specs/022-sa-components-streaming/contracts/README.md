# Contracts — `022-sa-components-streaming`

Cópias byte a byte dos contratos do Architecture doc no pin vigente. Não edite estes arquivos aqui. Uma mudança de contrato nasce em `weni-ai/vtex-cx-experience-specs` e chega por um novo pin.

| Arquivo | Origem (pin `329a1db8c1f3f62208b052457e0e3bc9654ce102`) | git blob | SHA-256 |
|---|---|---|---|
| [openapi.flows.yaml](openapi.flows.yaml) (1.1.0) | https://github.com/weni-ai/vtex-cx-experience-specs/blob/329a1db8c1f3f62208b052457e0e3bc9654ce102/specs/019-sa-components-streaming/contracts/openapi.flows.yaml | `1d651ee14a48902f6e02c22993538b3ddce19e00` | `604781847cc216388db239cbeeef41e9acdc456d239fbf4abcb0e4b7396e310e` |
| [components-shared.schema.json](components-shared.schema.json) (1.0.0) | https://github.com/weni-ai/vtex-cx-experience-specs/blob/329a1db8c1f3f62208b052457e0e3bc9654ce102/specs/019-sa-components-streaming/contracts/components-shared.schema.json | `802d634f4911fd24d07d10a644b1a551fa619fec` | `b1d4ab17da8a1bb3ff7bb22b0845206cf842ad91623e857a9edf902e3244ee36` |

- O `$ref: "./components-shared.schema.json#/$defs/..."` do OpenAPI resolve para o arquivo ao lado.
- O commit `fe00c1c` está obsoleto e não é contrato.
- A tag `019-sa-components-streaming/arch-v1` existe, mas a spec não se fixa nela enquanto o documento tagueado disser `Status: Draft` e a aprovação do `flows` estiver pendente. Quando isso mudar, re-fixar o pin, conferir os hashes acima e atualizar esta tabela.

Comportamento do `flows` sobre esse contrato, nos pontos em que o OpenAPI não define detalhe: [messages-stream.behavior.md](messages-stream.behavior.md).
