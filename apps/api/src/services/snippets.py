"""Download snippet 생성기 — 데이터셋 source 별 R / Python / Bash 코드 템플릿.

순수 함수 — DB 호출 없음. 입력은 (source_db, source_id) 외에 source-specific 옵션
(예: GEO 의 GPL platform). 결과는 사용자가 복사·붙여넣기 해서 그대로 실행 가능하도록
self-contained.

설계 결정:
- 각 source × lang 조합당 하나의 dataclass-like dict 반환:
    { "language": "R" | "python" | "bash",
      "title": str, "description": str, "code": str, "requires": list[str] }
- requires 는 사용자가 미리 설치해야 할 패키지 / 도구 (UI 가 별도로 표시).
- 코드 안의 accession 은 사용자 입력이 아닌 catalog 의 source_id 라 safe.
  단, 템플릿 substitution 은 단순 문자열 치환만 사용 (eval 등 금지).
"""
from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("R", "python", "bash")


def build_snippets(source_db: str, source_id: str, **opts: Any) -> list[dict[str, Any]]:
    """source 별 가용한 모든 snippet 반환. 알 수 없는 source 는 빈 리스트."""
    sid = source_id.strip()
    if not sid:
        return []
    db = source_db.upper()
    if db == "GEO":
        return _geo_snippets(sid)
    if db == "SRA":
        return _sra_snippets(sid)
    if db == "ENA":
        return _ena_snippets(sid)
    if db == "HCA":
        return _hca_snippets(sid)
    if db == "GDC":
        return _gdc_snippets(sid)
    return []


def _ena_snippets(accession: str) -> list[dict[str, Any]]:
    """ENA browser + portal API + fastq direct download.

    INSDC mirror — SRP/SRR/SRX/ERP accessions 모두 동작. 유럽 download 가
    SRA NA mirror 보다 빠를 수 있음 (네트워크 라우팅).
    """
    return [
        {
            "language": "bash",
            "title": "ENA — fastq 직접 다운로드 (filereport API)",
            "description": "ENA portal 의 filereport 로 fastq URL 조회 후 curl 로 다운로드. SRA prefetch 보다 단순.",
            "requires": ["curl", "(optional) aria2c — 병렬"],
            "code": (
                f'ACC="{accession}"\n'
                '# filereport 로 fastq URL + md5 가져오기\n'
                'curl -s "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=$ACC&result=read_run&fields=run_accession,fastq_ftp,fastq_md5&format=tsv" > "${ACC}_files.tsv"\n'
                'cat "${ACC}_files.tsv"\n'
                '# 첫 컬럼 run + fastq_ftp 추출 후 다운로드\n'
                'awk -F\\t \'NR>1 {split($2, a, ";"); for (f in a) print a[f]}\' "${ACC}_files.tsv" \\\n'
                '  | xargs -I{} curl -O "ftp://{}"\n'
            ),
        },
        {
            "language": "python",
            "title": "ENA portal API — Python (pandas)",
            "description": "ENA 의 filereport 응답을 pandas DataFrame 으로 로드 + 메타데이터 정렬.",
            "requires": ["pip install pandas requests"],
            "code": (
                "import pandas as pd\n"
                "\n"
                f'acc = "{accession}"\n'
                'url = f"https://www.ebi.ac.uk/ena/portal/api/filereport?accession={acc}&result=read_run&fields=run_accession,sample_alias,library_strategy,instrument_model,read_count,fastq_ftp&format=tsv"\n'
                'df = pd.read_csv(url, sep="\\t")\n'
                'print(df[["run_accession", "library_strategy", "instrument_model", "read_count"]])\n'
            ),
        },
    ]


def _geo_snippets(gse: str) -> list[dict[str, Any]]:
    return [
        {
            "language": "R",
            "title": "GEOquery — Series + ExpressionSet",
            "description": "BioConductor GEOquery 로 series matrix + expression 데이터 로드.",
            "requires": ["R (>=4.3)", "BiocManager::install('GEOquery')"],
            "code": (
                "# GEOquery — 한 줄로 series 메타데이터 + 발현 매트릭스를 ExpressionSet 으로\n"
                "library(GEOquery)\n"
                f'gse <- getGEO("{gse}", GSEMatrix = TRUE)\n'
                "# 여러 ExpressionSet 이 반환되면 첫 번째를 선택\n"
                "eset <- gse[[1]]\n"
                "pheno <- pData(eset)\n"
                "exprs_mat <- exprs(eset)\n"
                "cat(\"n_samples=\", ncol(exprs_mat), \" n_features=\", nrow(exprs_mat), \"\\n\", sep=\"\")\n"
            ),
        },
        {
            "language": "R",
            "title": "GEOquery — supplementary 파일 (raw)",
            "description": "원본 supplementary 파일(*.tar / *.txt.gz) 을 작업 디렉토리에 다운로드.",
            "requires": ["R (>=4.3)", "BiocManager::install('GEOquery')"],
            "code": (
                "library(GEOquery)\n"
                f'files <- getGEOSuppFiles("{gse}", makeDirectory = TRUE, fetch_files = TRUE)\n'
                "print(rownames(files))\n"
            ),
        },
        {
            "language": "python",
            "title": "GEOparse — Python 클라이언트",
            "description": "Python 환경에서 GEO series 를 dict-like 객체로 파싱.",
            "requires": ["pip install GEOparse"],
            "code": (
                "import GEOparse\n"
                "\n"
                f'gse = GEOparse.get_GEO(geo="{gse}", destdir="./geo_cache", silent=True)\n'
                'print(f"n_samples={len(gse.gsms)} n_platforms={len(gse.gpls)}")\n'
                "# 첫 sample 의 characteristics 출력\n"
                "first_gsm = next(iter(gse.gsms.values()))\n"
                'print(first_gsm.metadata.get("characteristics_ch1", []))\n'
            ),
        },
        {
            "language": "bash",
            "title": "wget — series matrix 직접 다운로드",
            "description": "FTP 에서 series matrix.txt.gz 파일을 직접 가져오기.",
            "requires": ["wget 또는 curl"],
            "code": (
                f'GSE="{gse}"\n'
                'STUB="${GSE%???}nnn"   # GSE176178 -> GSE176nnn\n'
                "URL=\"https://ftp.ncbi.nlm.nih.gov/geo/series/${STUB}/${GSE}/matrix/${GSE}_series_matrix.txt.gz\"\n"
                'wget -nc "$URL"\n'
            ),
        },
    ]


def _sra_snippets(srx_or_srp: str) -> list[dict[str, Any]]:
    return [
        {
            "language": "bash",
            "title": "SRA Toolkit — prefetch + fasterq-dump",
            "description": "공식 SRA Toolkit 으로 fastq 추출. .sra 캐시 + 압축 fastq 출력.",
            "requires": ["sra-toolkit (>=3.0)"],
            "code": (
                f'ACC="{srx_or_srp}"\n'
                'prefetch "$ACC" -O ./sra_cache\n'
                'fasterq-dump "./sra_cache/$ACC" -O ./fastq -e 8 --split-files\n'
                "ls -lh ./fastq\n"
            ),
        },
        {
            "language": "python",
            "title": "pysradb — 메타데이터 조회",
            "description": "study 의 모든 run 메타데이터를 pandas DataFrame 으로 로드.",
            "requires": ["pip install pysradb"],
            "code": (
                "from pysradb import SRAweb\n"
                "\n"
                "db = SRAweb()\n"
                f'meta = db.sra_metadata("{srx_or_srp}", detailed=True)\n'
                'print(meta[["run_accession", "library_strategy", "library_layout", "instrument"]])\n'
            ),
        },
    ]


def _hca_snippets(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "language": "bash",
            "title": "curl — HCA Azul Data Browser",
            "description": "프로젝트 메타데이터(JSON) 및 manifest 다운로드.",
            "requires": ["curl"],
            "code": (
                f'PROJECT="{project_id}"\n'
                'curl -s "https://service.azul.data.humancellatlas.org/index/projects/${PROJECT}" '
                "| jq '.projects[0] | {id: .projectId, title: .projectTitle, contributors: .contributors|length}'\n"
            ),
        },
        {
            "language": "python",
            "title": "Python — HCA matrix manifest",
            "description": "Cell counts matrix 의 manifest 를 가져와 다운로드 후보 확인.",
            "requires": ["pip install requests"],
            "code": (
                "import requests\n"
                "\n"
                f'project_id = "{project_id}"\n'
                'url = f"https://service.azul.data.humancellatlas.org/index/projects/{project_id}"\n'
                "resp = requests.get(url, timeout=30)\n"
                "resp.raise_for_status()\n"
                "data = resp.json()\n"
                'print(data["projects"][0]["projectTitle"])\n'
            ),
        },
    ]


def _gdc_snippets(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "language": "python",
            "title": "GDC REST API — case 메타데이터",
            "description": "프로젝트의 case 목록 + demographic 정보를 페이지네이션으로 fetch.",
            "requires": ["pip install requests"],
            "code": (
                "import requests\n"
                "\n"
                f'project_id = "{project_id}"\n'
                'url = "https://api.gdc.cancer.gov/cases"\n'
                "filters = {\n"
                '    "op": "in",\n'
                '    "content": {"field": "project.project_id", "value": [project_id]},\n'
                "}\n"
                "params = {\n"
                '    "filters": __import__("json").dumps(filters),\n'
                '    "fields": "case_id,submitter_id,demographic.gender,demographic.race,diagnoses.primary_diagnosis",\n'
                '    "format": "JSON",\n'
                '    "size": 100,\n'
                "}\n"
                "resp = requests.get(url, params=params, timeout=30)\n"
                "resp.raise_for_status()\n"
                'print(len(resp.json()["data"]["hits"]), "cases")\n'
            ),
        },
    ]
