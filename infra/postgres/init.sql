-- Расширения, нужные для каталога.
--   pg_trgm  — триграммный индекс + similarity() для fuzzy-match оффер'ов на games (этап 5)
--   unaccent — снятие диакритики, чтобы 'Сапёр' и 'Сапер' матчились одинаково

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
