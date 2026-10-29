# Convenience wrapper around docker compose.
.PHONY: install up down logs restart update ps backup

install:
	@bash install.sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f backend

restart:
	docker compose restart backend proxy

ps:
	docker compose ps

# Back up the database + config + uploaded certs/logos to ./backup.tar.gz
backup:
	docker run --rm -v xyberah_data:/data -v xyberah_config:/config -v xyberah_certs:/certs \
	  -v "$(PWD)":/out alpine tar czf /out/backup.tar.gz /data /config /certs
	@echo "Wrote backup.tar.gz"
