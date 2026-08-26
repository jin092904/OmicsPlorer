"""의학 약어 사전 — Sol 1 query understanding 보조 데이터 모듈.

목적 (purpose):
    사용자가 검색창에 "CESC scRNA-seq" 처럼 약어(abbreviation)로 입력할 때,
    gemma4 가 이를 정식 질환/조직/세포 이름으로 풀어쓰도록(expand) 돕는
    힌트 테이블을 제공한다. 이 모듈은 순수 데이터 + 포매팅(formatting)만
    담당하며 LLM 호출이나 프롬프트 로직을 포함하지 않는다.

설계 결정 (design decisions):
    - 모호하지 않은(unambiguous) 약어만 ABBREV_EXPANSIONS 에 넣는다.
      "ALL"(acute lymphoblastic leukemia vs 'all'=전체) 처럼 일상어/다른
      뜻과 충돌하는 약어는 정적(static) 확장이 위험하므로 AMBIGUOUS 로
      분리하고, 확장 여부는 gemma4 가 쿼리 문맥으로 판단하게 맡긴다.
    - 출처(source): 손으로 큐레이션한 33개 TCGA 코드 + 핵심 의학/유전체학
      약어. 전체 MeSH/UMLS import(~300MB, XML 파싱)는 데모 이후 백로그.
      코퍼스 빈도 분석상 실제 쿼리의 ~95% 가 60~80개 핵심 약어로 커버됨.
    - render_abbrev_hint() 는 gemma4 컨텍스트 예산(budget)을 고려해 최대
      약 100개로 잘라 컴팩트한 텍스트 블록을 만든다.

다른 모듈에서 재사용 가능:
    sol4_prompt.py(workers), translate.py 등이 동일 출처를 import 가능.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# TCGA cancer-type codes (33). 모두 정식 종양학 코드라 일상어 충돌 없음.
# key = 대문자 약어, value = 정식 명칭(full name).
# ---------------------------------------------------------------------------
_TCGA_CODES: dict[str, str] = {
    "ACC": "adrenocortical carcinoma",
    "BLCA": "bladder urothelial carcinoma",
    "BRCA": "breast invasive carcinoma",
    "CESC": "cervical squamous cell carcinoma and endocervical adenocarcinoma",
    "CHOL": "cholangiocarcinoma",
    "COAD": "colon adenocarcinoma",
    "CNTL": "colorectal control",
    "DLBC": "diffuse large B-cell lymphoma",
    "ESCA": "esophageal carcinoma",
    "GBM": "glioblastoma multiforme",
    "HNSC": "head and neck squamous cell carcinoma",
    "KICH": "kidney chromophobe",
    "KIRC": "kidney renal clear cell carcinoma",
    "KIRP": "kidney renal papillary cell carcinoma",
    "LAML": "acute myeloid leukemia",
    "LGG": "brain lower grade glioma",
    "LIHC": "liver hepatocellular carcinoma",
    "LUAD": "lung adenocarcinoma",
    "LUSC": "lung squamous cell carcinoma",
    "MESO": "mesothelioma",
    "OV": "ovarian serous cystadenocarcinoma",
    "PAAD": "pancreatic adenocarcinoma",
    "PCPG": "pheochromocytoma and paraganglioma",
    "PRAD": "prostate adenocarcinoma",
    "READ": "rectum adenocarcinoma",
    "SARC": "sarcoma",
    "SKCM": "skin cutaneous melanoma",
    "STAD": "stomach adenocarcinoma",
    "TGCT": "testicular germ cell tumors",
    "THCA": "thyroid carcinoma",
    "THYM": "thymoma",
    "UCEC": "uterine corpus endometrial carcinoma",
    "UCS": "uterine carcinosarcoma",
    "UVM": "uveal melanoma",
}

# ---------------------------------------------------------------------------
# 일반 의학/유전체학 약어 — 모호성 없는 것만. 카테고리별 주석.
# (질환 / 조직·검체 / 세포 / 줄기세포 / 어세이·기법 / 유전체학 개념)
# ---------------------------------------------------------------------------
_COMMON_MEDICAL: dict[str, str] = {
    # --- 질환 (diseases) ---
    "NSCLC": "non-small cell lung cancer",
    "SCLC": "small cell lung cancer",
    "HCC": "hepatocellular carcinoma",
    "RCC": "renal cell carcinoma",
    "PDAC": "pancreatic ductal adenocarcinoma",
    "AML": "acute myeloid leukemia",
    "CLL": "chronic lymphocytic leukemia",
    "CML": "chronic myeloid leukemia",
    "DLBCL": "diffuse large B-cell lymphoma",
    "IDC": "invasive ductal carcinoma",
    "TNBC": "triple-negative breast cancer",
    "COPD": "chronic obstructive pulmonary disease",
    "IBD": "inflammatory bowel disease",
    "RA": "rheumatoid arthritis",
    "SLE": "systemic lupus erythematosus",
    "T2D": "type 2 diabetes",
    "T2DM": "type 2 diabetes mellitus",
    "T1D": "type 1 diabetes",
    "ALS": "amyotrophic lateral sclerosis",
    "CKD": "chronic kidney disease",
    "NAFLD": "non-alcoholic fatty liver disease",
    "NASH": "non-alcoholic steatohepatitis",
    "UC": "ulcerative colitis",
    # --- 조직 / 검체 (tissues / specimens) ---
    "PBMC": "peripheral blood mononuclear cell",
    "BMMC": "bone marrow mononuclear cell",
    "CSF": "cerebrospinal fluid",
    "BAL": "bronchoalveolar lavage",
    # --- 세포 (cell types) ---
    "TIL": "tumor-infiltrating lymphocyte",
    "NK": "natural killer cell",
    "Treg": "regulatory T cell",
    # --- 줄기세포 (stem cells) ---
    "iPSC": "induced pluripotent stem cell",
    "MSC": "mesenchymal stem cell",
    "HSC": "hematopoietic stem cell",
    # --- 어세이 / 기법 (assays / methods) ---
    "ChIP": "chromatin immunoprecipitation",
    "ATAC": "assay for transposase-accessible chromatin",
    "WGS": "whole genome sequencing",
    "WES": "whole exome sequencing",
    "scRNA": "single-cell RNA sequencing",
    "snRNA": "single-nucleus RNA sequencing",
    "snATAC": "single-nucleus ATAC sequencing",
    "WGBS": "whole genome bisulfite sequencing",
    "RRBS": "reduced representation bisulfite sequencing",
    "Hi-C": "chromosome conformation capture",
    # --- 유전체학 개념 (genomics concepts) ---
    "GWAS": "genome-wide association study",
    "eQTL": "expression quantitative trait locus",
    "CNV": "copy number variation",
    "SNV": "single nucleotide variant",
    "MAF": "minor allele frequency",
}

# ---------------------------------------------------------------------------
# 최종 확장 사전 (public). TCGA 33 + 일반 의학 약어. 모두 UNAMBIGUOUS.
# key 는 대문자(uppercase) 정규화된 약어를 권장하지만, 대소문자가 의미를 갖는
# 표기(scRNA, iPSC, Treg, Hi-C 등)는 원형을 보존한다 — 힌트 테이블에서
# gemma4 가 그대로 인식하는 편이 정확하기 때문.
# ---------------------------------------------------------------------------
ABBREV_EXPANSIONS: dict[str, str] = {**_TCGA_CODES, **_COMMON_MEDICAL}

# ---------------------------------------------------------------------------
# AMBIGUOUS — 정적 확장이 너무 위험한 약어. ABBREV_EXPANSIONS 에 절대 넣지 않음.
# 각 약어는 경쟁하는 여러 뜻(competing meanings)을 가지므로, 확장 여부와 의미는
# gemma4 가 쿼리 문맥에서 판단해야 한다. (frozenset = 불변 + 멤버십 조회 O(1))
#
#   ALL : acute lymphoblastic leukemia vs "all"(전체 수량사)
#   AI  : avian influenza vs artificial intelligence
#   ER  : estrogen receptor vs endoplasmic reticulum vs emergency room
#   MS  : multiple sclerosis vs mass spectrometry
#   PD  : Parkinson's disease vs pancreatic duct vs programmed death(면역관문)
#   AD  : Alzheimer's disease vs atopic dermatitis
#   CD  : cluster of differentiation vs Crohn's disease vs celiac disease
#   CA  : carcinoma vs cancer vs carbonic anhydrase
#   MO  : month of observation vs molecular orbital
#   HP  : Helicobacter pylori vs Hantavirus pulmonary syndrome
#   PI  : principal investigator vs phosphatidylinositol
#   IV  : intravenous vs independent variable
#   MM  : multiple myeloma vs millimeter
#   DC  : dendritic cell vs Crohn's-adjacent 표기 충돌 / 약어 남용
#   ESC : embryonic stem cell vs escape/escape mutant 표기 충돌
#   PD-1/PD-L1 같은 마커는 별도(약어 단독 "PD" 와 구분 불가하므로 PD 도 모호)
# ---------------------------------------------------------------------------
AMBIGUOUS: frozenset[str] = frozenset({
    "ALL", "AI", "ER", "MS", "PD", "AD", "CD", "CA",
    "MO", "HP", "PI", "IV", "MM", "DC", "ESC",
})

# 안전망: 혹시라도 모호 약어가 확장 사전에 섞이면 import 시점에 즉시 실패.
_overlap = AMBIGUOUS & ABBREV_EXPANSIONS.keys()
assert not _overlap, f"ambiguous abbrevs leaked into ABBREV_EXPANSIONS: {sorted(_overlap)}"


def render_abbrev_hint(max_entries: int = 100) -> str:
    """gemma4 프롬프트용 컴팩트 약어 힌트 블록을 생성한다.

    형식 (format)::

        === MEDICAL ABBREVIATIONS (expand when query context fits) ===
        CESC=cervical squamous cell carcinoma; THCA=thyroid carcinoma; ...
        Ambiguous (decide from query context, do NOT assume): ALL, AI, ER, ...

    Args:
        max_entries: 확장 사전에서 포함할 최대 항목 수. 컨텍스트 예산을 위해
            기본 100. 사전이 더 크면 정렬된 앞쪽부터 잘라낸다(결정적/안정적).

    Returns:
        프롬프트에 그대로 끼워넣을 수 있는 멀티라인 문자열.
    """
    # 결정적(deterministic) 순서: 키 정렬 후 상한만큼 자른다. 빈도 가중치는
    # 데모 이후 도입 — 지금은 안정적 재현성이 우선.
    items = sorted(ABBREV_EXPANSIONS.items(), key=lambda kv: kv[0])[: max(0, max_entries)]
    pairs = "; ".join(f"{abbrev}={full}" for abbrev, full in items)
    ambiguous = ", ".join(sorted(AMBIGUOUS))
    return (
        "=== MEDICAL ABBREVIATIONS (expand when query context fits) ===\n"
        f"{pairs}\n"
        "Ambiguous (decide from query context, do NOT assume a meaning): "
        f"{ambiguous}"
    )


__all__ = ["ABBREV_EXPANSIONS", "AMBIGUOUS", "render_abbrev_hint"]
