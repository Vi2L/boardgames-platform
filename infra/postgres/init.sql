-- Расширения, нужные для каталога.
--   pg_trgm  — триграммный индекс + similarity() для fuzzy-match оффер'ов на games (этап 5)
--   unaccent — снятие диакритики, чтобы 'Сапёр' и 'Сапер' матчились одинаково
--   vector   — pgvector для cosine similarity (matching v2: bge-m3 эмбеддинги)

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS vector;
