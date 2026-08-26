-- Small synthetic corpus for the Docker demo profile. Idempotent and clearly non-production.
INSERT INTO datasets (
  source_db, source_id, title, abstract, modality, organism_taxid, n_samples,
  disease_ids, tissue_ids, cell_type_ids, access_type, has_processed_data,
  has_raw_data, metadata_completeness, platform, library_strategy,
  submission_date, raw_metadata, extraction_version
) VALUES
('DEMO','DEMO-PDAC-SCRNA','Single-cell atlas of pancreatic ductal adenocarcinoma','Synthetic demo record: tumor and adjacent pancreatic tissue profiled by single-cell RNA sequencing.',ARRAY['scRNA-seq'],ARRAY[9606],24,ARRAY['MONDO:0005180'],ARRAY['UBERON:0001264'],ARRAY['CL:0000182'],'open',true,true,0.95,'Illumina NovaSeq','RNA-Seq','2026-01-01','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-PBMC-LUPUS','Case-control whole-blood transcriptomics in systemic lupus erythematosus','Synthetic demo record: lupus cases and healthy controls with paired clinical metadata.',ARRAY['bulk RNA-seq'],ARRAY[9606],80,ARRAY['MONDO:0007915'],ARRAY['UBERON:0000178'],ARRAY[]::text[],'open',true,true,0.92,'Illumina NovaSeq','RNA-Seq','2026-01-02','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-BRCA','Breast carcinoma multi-omics cohort','Synthetic demo record: breast tumor RNA sequencing and DNA methylation with controlled clinical access.',ARRAY['bulk RNA-seq','DNA methylation'],ARRAY[9606],120,ARRAY['MONDO:0007254'],ARRAY['UBERON:0000310'],ARRAY[]::text[],'controlled',true,true,0.90,'Illumina HiSeq','RNA-Seq','2026-01-03','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-GBM','Glioblastoma tumor microenvironment single-cell study','Synthetic demo record: malignant, myeloid, and T-cell populations in brain tumor samples.',ARRAY['scRNA-seq'],ARRAY[9606],32,ARRAY['MONDO:0018177'],ARRAY['UBERON:0000955'],ARRAY['CL:0000763','CL:0000623'],'open',true,true,0.94,'10x Genomics','RNA-Seq','2026-01-04','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-CRC-PAIRED','Paired colorectal tumor and adjacent normal RNA-seq','Synthetic demo record: matched tumor-normal samples from colorectal cancer subjects.',ARRAY['bulk RNA-seq'],ARRAY[9606],40,ARRAY['MONDO:0005575'],ARRAY['UBERON:0001155'],ARRAY[]::text[],'open',true,true,0.91,'Illumina NovaSeq','RNA-Seq','2026-01-05','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-COVID','Longitudinal immune response after SARS-CoV-2 infection','Synthetic demo record: PBMC single-cell profiles across acute and convalescent time points.',ARRAY['scRNA-seq'],ARRAY[9606],60,ARRAY['MONDO:0100096'],ARRAY['UBERON:0000178'],ARRAY['CL:0000542'],'open',true,true,0.93,'10x Genomics','RNA-Seq','2026-01-06','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-MOUSE-LIVER','Mouse liver dose-response toxicogenomics','Synthetic demo record: mouse liver RNA-seq after graded compound exposure.',ARRAY['bulk RNA-seq'],ARRAY[10090],48,ARRAY[]::text[],ARRAY['UBERON:0002107'],ARRAY['CL:0000182'],'open',true,true,0.88,'Illumina NextSeq','RNA-Seq','2026-01-07','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-ATAC','Chromatin accessibility in human hematopoietic stem cells','Synthetic demo record: ATAC-seq of purified bone marrow stem and progenitor cells.',ARRAY['ATAC-seq'],ARRAY[9606],18,ARRAY[]::text[],ARRAY['UBERON:0002371'],ARRAY['CL:0000037'],'open',true,true,0.89,'Illumina NovaSeq','ATAC-seq','2026-01-08','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-CHIP','H3K4me3 ChIP-seq during neuronal differentiation','Synthetic demo record: time-course histone mark profiling during neural differentiation.',ARRAY['ChIP-seq'],ARRAY[9606],16,ARRAY[]::text[],ARRAY['UBERON:0000955'],ARRAY['CL:0000540'],'open',true,true,0.87,'Illumina HiSeq','ChIP-Seq','2026-01-09','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-SPATIAL','Spatial transcriptomics of breast tumor margins','Synthetic demo record: spatial gene expression across tumor core and invasive margin.',ARRAY['spatial transcriptomics'],ARRAY[9606],12,ARRAY['MONDO:0007254'],ARRAY['UBERON:0000310'],ARRAY[]::text[],'open',true,true,0.90,'Visium','Spatial Transcriptomics','2026-01-10','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-METAGENOME','Human gut microbiome shotgun metagenomics','Synthetic demo record: stool metagenomes from inflammatory bowel disease cases and controls.',ARRAY['metagenomics'],ARRAY[9606],100,ARRAY['MONDO:0005265'],ARRAY['UBERON:0001988'],ARRAY[]::text[],'open',false,true,0.82,'Illumina NovaSeq','WGS','2026-01-11','{"demo":true}'::jsonb,'demo-v1'),
('DEMO','DEMO-PROTEOMICS','Plasma proteomics in multiple myeloma','Synthetic demo record: longitudinal plasma proteomics before and after therapy.',ARRAY['proteomics'],ARRAY[9606],45,ARRAY['MONDO:0009693'],ARRAY['UBERON:0001969'],ARRAY['CL:0000786'],'open',true,true,0.86,'Orbitrap','Mass Spectrometry','2026-01-12','{"demo":true}'::jsonb,'demo-v1')
ON CONFLICT (source_db, source_id) DO UPDATE SET
  title = EXCLUDED.title,
  abstract = EXCLUDED.abstract,
  modality = EXCLUDED.modality,
  organism_taxid = EXCLUDED.organism_taxid,
  n_samples = EXCLUDED.n_samples,
  disease_ids = EXCLUDED.disease_ids,
  tissue_ids = EXCLUDED.tissue_ids,
  cell_type_ids = EXCLUDED.cell_type_ids,
  access_type = EXCLUDED.access_type,
  has_processed_data = EXCLUDED.has_processed_data,
  has_raw_data = EXCLUDED.has_raw_data,
  metadata_completeness = EXCLUDED.metadata_completeness,
  platform = EXCLUDED.platform,
  library_strategy = EXCLUDED.library_strategy,
  submission_date = EXCLUDED.submission_date,
  raw_metadata = EXCLUDED.raw_metadata,
  extraction_version = EXCLUDED.extraction_version,
  updated_at = now();
