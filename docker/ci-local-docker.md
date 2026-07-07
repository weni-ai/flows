Como rodar os testes em containers

Execute a partir da raiz do projeto.

## Loop de desenvolvimento (mais rápido, recomendado)

Mantém PostGIS, Redis e um container persistente de pé; o código entra por bind mount
(sem rebuild/cópia) e o banco de teste é reutilizado (--keepdb). Depois do primeiro
comando, cada rodada custa só o tempo do próprio teste.

# rodar um app
./docker/test temba.flows
# rodar um teste específico
./docker/test temba.flows.tests:FlowTest.test_prune_recent_runs
# rodar tudo
./docker/test

## Execução one-shot (igual ao CI, recria o container a cada vez)

docker compose -f docker/docker-compose.test.yml run --rm test temba.flows
docker compose -f docker/docker-compose.test.yml run --rm test temba.flows temba.msgs
docker compose -f docker/docker-compose.test.yml run --rm test ""

## Derrubar tudo

docker compose -f docker/docker-compose.test.yml down -v
