# Financial Complaint Router

An AI system that reads a customer's financial complaint and **routes it to the right team**, **flags urgent cases**, gives a **confidence score with an explanation** and shows **similar past complaints**. It is built and operated with a full AIOps lifecycle:

| Concern | Tooling in this repo |
|---|---|
| Data engineering | **Ray Data** distributed cleaning (`src/complaint_router/pipeline/preprocess.py`) |
| Pipeline / CI | **DVC** DAG (`dvc.yaml`): unit tests → ingest → preprocess → validate → split → train → evaluate → register; git pre-push hook |
| Versioning | **Git** (code), **DVC** + local remote (data, models), **Git LFS** (sample dataset) |
| Experiment tracking | **MLflow** (autolog + custom params/metrics/tags/artifacts), Model Registry with `@champion` |
| Serving | **MLflow** `models serve` behind a **FastAPI** backend; static web UI on nginx (REST only) |
| Packaging | **Docker** + **Docker Compose** (10 services), **MLproject** |
| Monitoring | **Prometheus**, **Grafana**, **Alertmanager**; drift → automatic retraining |

Docs: [architecture](docs/architecture.md) · [HLD](docs/HLD.md) · [LLD / API](docs/LLD.md) · [test plan](docs/test_plan.md) · [test report](docs/test_report.md) · [user manual](docs/user_manual.md)

---

## Quick start on Ubuntu (VirtualBox VM)

**VM sizing:** 4 vCPU, **8 GB RAM** (6 GB minimum), 30 GB disk, Ubuntu 22.04 or 24.04.

```bash
# 1. get the code into the VM (git clone, or copy the folder via a shared folder)
cd ~/AIOps_project

# 2. one-time setup: docker, git-lfs, venv, git + dvc init, secrets, git hooks
bash scripts/setup_ubuntu.sh
newgrp docker            # only needed the first time docker was installed

# 3. start the stack (first build downloads images and wheels: ~10 min)
make up

# 4. train the first model on real CFPB data (downloads 114 MB, ~5 min)
make train               # or: make train-sample  (bundled sample, ~1 min, offline)

# 5. check everything
make smoke
```

Open **http://localhost:8080**. Within ~20 s of training finishing, the status light turns green.

| Service | URL | Notes |
|---|---|---|
| Web app | http://localhost:8080 | for agents |
| API docs (Swagger) | http://localhost:8000/docs | REST contract |
| MLflow | http://localhost:5000 | experiments + registry |
| Grafana | http://localhost:3000 | anonymous view; admin password in `.env` |
| Prometheus | http://localhost:9090 | targets, alerts |
| Alertmanager | http://localhost:9093 | drift → retrain routing |

**Opening it from Windows (host) instead of inside the VM:** in VirtualBox → *Settings → Network → Adapter 1 (NAT) → Port Forwarding*, add rules host port = guest port for 8080, 8000, 3000, 5000, 9090 and 9093. Then use the same `localhost` URLs in your Windows browser. (Alternatively use a *Host-only* adapter and browse to the VM's IP. The UI derives the API address from the page address automatically.)

## Everyday commands

```bash
make help            # list everything
make ps / logs       # service status / logs
make train           # dvc repro in the ML container (only changed stages re-run)
make dag             # print the pipeline DAG
make metrics         # dvc metrics show
make venv            # host virtualenv for tests & lint
make lint test       # ruff + unit/integration tests
make report          # regenerate docs/test_report.md
make ci              # full local CI (lint, tests, report, dvc status, docker build)
make test-e2e        # tests against the running stack
make drift           # demo: send drifted traffic → alert → automatic retraining
make rollback VERSION=1
make down
```

## Reproducing an experiment

Every MLflow run is tagged with the **git commit**, the **MD5 of the train/val data** and the trigger. To reproduce run *X*:

```bash
git checkout <git_commit tag of run X>
dvc checkout           # restores the exact data / model versions from the DVC cache/remote
make train             # identical params.yaml → identical pipeline
```

Experiments with other hyper-parameters (each one logged to MLflow and DVC):

```bash
docker compose run --rm retrainer dvc exp run -S train.model_type=sgd -S train.alpha=0.00005
docker compose run --rm retrainer dvc exp show
# or with MLflow Projects:
docker compose run --rm retrainer mlflow run . -e train -P model_type=cnb --env-manager local
```

Version data and models in the local DVC remote (`~/dvc-storage`, no cloud):

```bash
.venv/bin/dvc push        # after a successful training
git add dvc.lock params.yaml reports/*.json && git commit -m "model: ..."
```

## Repository layout

```
src/complaint_router/      shared library: cleaning, taxonomy, model, drift, pipeline stages
backend/app/               FastAPI service (REST API, metrics, drift monitor, feedback)
frontend/                  static web UI + nginx (talks to the API only)
services/model_server/     supervisor around `mlflow models serve` (follows @champion)
services/retrainer/        Alertmanager webhook → dvc repro
monitoring/                prometheus.yml, alert rules, alertmanager, grafana provisioning
docker/ml.Dockerfile       multi-stage image: mlflow / model-server / retrainer
dvc.yaml params.yaml       the pipeline and all its parameters
MLproject python_env.yaml  MLflow project definition
tests/                     unit, integration, e2e
scripts/                   setup, CI, smoke test, drift demo, rollback, report generator
docs/                      architecture, HLD, LLD, test plan/report, user manual
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `permission denied ... docker.sock` | `newgrp docker` or log out/in after setup |
| `ADMIN_TOKEN ... run "make env" first` | `make env` (creates `.env`) |
| UI says *Model offline* | no model trained yet → `make train`; check `docker compose logs model-server` |
| Ray `OutOfMemory` / container killed | raise VM RAM, or set `preprocess.num_cpus: 1` / `split.max_per_class: 3000` in `params.yaml` |
| Retrainer cannot write files | `.env` `HOST_UID/HOST_GID` must match `id -u` / `id -g` |
| Download of the dataset fails | set `ingest.source: sample` in `params.yaml` (offline sample) |

## Data source and licence

CFPB Consumer Complaint Database (public domain, US Government), via the Apache-2.0 parquet mirror `davidheineman/consumer-finance-complaints-large` on HuggingFace. The live CFPB export no longer includes the narrative text. The bundled `data/sample/sample_complaints.csv` holds 2,250 real complaints (250 per category).
