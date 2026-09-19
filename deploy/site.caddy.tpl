# 도면 공간구문 스튜디오 — 사이트 블록
# /etc/caddy/conf.d/__DOMAIN__.caddy 로 설치된다.
__DOMAIN__ {
	root * __WEBROOT__
	encode zstd gzip
	file_server

	header {
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
		Permissions-Policy "geolocation=(), microphone=(), camera=()"
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		-Server
		Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
	}

	@html path / *.html
	header @html Cache-Control "no-cache, must-revalidate"

	@assets path *.css *.js *.woff2 *.png *.jpg *.svg *.ico
	header @assets Cache-Control "public, max-age=31536000, immutable"

	redir /grid      /grid-editor.html
	redir /syntax    /syntax-report.html
	redir /benchmark /benchmark-report.html
}

www.__DOMAIN__ {
	redir https://__DOMAIN__{uri} permanent
}
