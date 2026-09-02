.PHONY: setup up down test test-db lint dados exemplo migrate migration check-drift

setup:
	pip install -r requirements.txt
	cp -n .env.example .env || true

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

test:
	pytest tests/ -v

test-db:
	DATABASE_URL_TEST=$${DATABASE_URL} pytest tests/ -v

migrate:
	alembic upgrade head

migration:
	alembic revision --autogenerate -m "$(m)"

# falha se models.py divergir do schema aplicado
check-drift:
	@alembic revision --autogenerate -m _drift 2>&1 | grep -i detected \
	  && (rm -f db/migrations/versions/*_drift.py; echo "DIVERGENCIA detectada"; exit 1) \
	  || (rm -f db/migrations/versions/*_drift.py; echo "schema em dia")

lint:
	ruff check . && ruff format --check .

dados:
	python scripts/gerar_teste.py --saida /tmp/t1.tif --lado 800
	python scripts/gerar_teste.py --saida /tmp/t2.tif --lado 800 --seed 2
	python scripts/gerar_teste.py --saida /tmp/big.tif --lado 6000 --sensor indice_pronto

exemplo: dados
	python cli.py /tmp/t1.tif --zonas 5 --mediana 5 --saida /tmp/out -v
