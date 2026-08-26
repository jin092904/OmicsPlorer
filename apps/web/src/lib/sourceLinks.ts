// 외부 출처(원본) 링크 생성기 — ResultCard 와 상세페이지가 공유.
//
// 주의(중요): source_db="SRA" 로 수집된 레코드의 source_id 는 실제로는 전부
// BioProject 번호(PRJ…)다(런/스터디 번호 SRR·SRP 가 아님). 과거에는 이를 무조건
//   https://www.ncbi.nlm.nih.gov/sra?term=PRJ…
// 로 보냈는데, 이 SRA 런 검색은 "그 프로젝트에 NCBI SRA 로 색인된 시퀀싱 런이
// 있을 때"만 결과가 나온다. 데이터가 GEO/ENA/DDBJ/CNCB 에 있거나, 16S 앰플리콘이라
// SRA 미색인이거나, 등록만 된 프로젝트면 NCBI 가 "No items found" 를 띄웠다.
//
// 해결: BioProject 번호는 prefix 로 출신 보관소를 판별해 그 보관소의 BioProject
// 페이지로 보낸다. (PRJNA→미국 NCBI, PRJEB→유럽 ENA, PRJDB→일본 DDBJ, PRJCA→중국 CNCB)
// 출신 보관소 페이지는 색인 런 유무와 무관하게 항상 열리고, 거기서 실제 데이터
// (런·파일·다운로드)로 이동할 수 있다.

// BioProject accession(PRJ…) → 출신 보관소의 프로젝트 페이지
function bioprojectUrl(id: string): string {
  if (/^PRJE[AB]/i.test(id)) return `https://www.ebi.ac.uk/ena/browser/view/${id}`; // ENA (PRJEB 및 레거시 PRJEA)
  if (/^PRJD[AB]/i.test(id)) return `https://ddbj.nig.ac.jp/resource/bioproject/${id}`; // DDBJ (PRJDB 및 레거시 PRJDA)
  if (/^PRJCA/i.test(id)) return `https://ngdc.cncb.ac.cn/bioproject/browse/${id}`; // CNCB/NGDC (중국)
  // PRJNA 및 그 외 INSDC BioProject → NCBI BioProject
  return `https://www.ncbi.nlm.nih.gov/bioproject/${id}`;
}

// source_db / source_id 로 외부 원본 URL 을 만든다. 매핑 없으면 undefined.
export function sourceUrl(sourceDb: string, sourceId: string): string | undefined {
  if (!sourceId) return undefined;
  switch (sourceDb) {
    case "GEO":
      return `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${sourceId}`;
    case "SRA":
      // 수집분은 source_id 가 BioProject 번호 → 출신 보관소로.
      if (/^PRJ/i.test(sourceId)) return bioprojectUrl(sourceId);
      // 방어적: 혹시 런/스터디 번호라면 기존 SRA 검색 유지.
      return `https://www.ncbi.nlm.nih.gov/sra?term=${sourceId}`;
    case "ENA":
      // ENA 직수집분도 PRJ 번호면 동일 규칙으로 출신 보관소 판별.
      if (/^PRJ/i.test(sourceId)) return bioprojectUrl(sourceId);
      return `https://www.ebi.ac.uk/ena/browser/view/${sourceId}`;
    case "HCA":
      return `https://data.humancellatlas.org/explore/projects/${sourceId}`;
    case "GDC":
      return `https://portal.gdc.cancer.gov/projects/${sourceId}`;
    default:
      return undefined;
  }
}

// 출처 버튼에 띄울 "목적지" 짧은 라벨. SRA/ENA 수집분은 source_id 가 BioProject 번호라
// 실제로 열리는 보관소(ENA/DDBJ/CNCB/BioProject)를 보여줘 "열기 SRA"→"열기 ENA" 같은
// 라벨↔목적지 불일치를 없앤다.
export function sourceLinkLabel(sourceDb: string, sourceId: string): string {
  if ((sourceDb === "SRA" || sourceDb === "ENA") && /^PRJ/i.test(sourceId)) {
    if (/^PRJE[AB]/i.test(sourceId)) return "ENA";
    if (/^PRJD[AB]/i.test(sourceId)) return "DDBJ";
    if (/^PRJCA/i.test(sourceId)) return "CNCB";
    return "BioProject";
  }
  return sourceDb; // GEO / GDC / HCA
}
