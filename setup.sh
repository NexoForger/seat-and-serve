#!/usr/bin/env bash
# Interactive local Docker setup for S&S (Seat & Serve).
set -Eeuo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_DIR="$(cd "$APP_DIR/../.." && pwd)"
PROJECT_DIR="$(cd "$APP_DIR/../../../.." && pwd)"
CONTAINER_BENCH=/workspace/development/frappe-bench
CONTAINER_APP="$CONTAINER_BENCH/apps/table_remote_till"
DRY_RUN=0

if [[ ${1:-} == --dry-run ]]; then
	DRY_RUN=1
elif [[ $# -ne 0 ]]; then
	printf 'Usage: %s [--dry-run]\n' "$0" >&2
	exit 2
fi

ask() {
	local reply
	read -r -p "$1 [$2]: " reply
	printf '%s' "${reply:-$2}"
}

ask_yes() {
	local reply
	reply="$(ask "$1" "$2")"
	reply="$(printf '%s' "$reply" | tr '[:upper:]' '[:lower:]')"
	case "$reply" in
		y|yes) return 0 ;;
		n|no) return 1 ;;
		*) printf 'Please answer yes or no.\n' >&2; exit 2 ;;
	esac
}

compose() {
	local -a env_args=()
	if [[ -f "$PROJECT_DIR/.env" ]]; then
		env_args=(--env-file "$PROJECT_DIR/.env")
	fi
	docker compose "${env_args[@]}" -p "$project" \
		-f "$PROJECT_DIR/devcontainer-example/docker-compose.yml" \
		-f "$PROJECT_DIR/compose.local.yaml" "$@"
}

if [[ ! -f "$PROJECT_DIR/devcontainer-example/docker-compose.yml" || ! -f "$PROJECT_DIR/compose.local.yaml" ]]; then
	printf 'This script needs the project Docker Compose files in %s.\n' "$PROJECT_DIR" >&2
	exit 1
fi
if [[ ! -f "$BENCH_DIR/apps/frappe/frappe/hooks.py" || ! -f "$BENCH_DIR/apps/erpnext/erpnext/hooks.py" || ! -f "$BENCH_DIR/apps/hrms/hrms/hooks.py" ]]; then
	printf 'Frappe, ERPNext and HRMS must already be present in %s/apps.\n' "$BENCH_DIR" >&2
	exit 1
fi

default_site=development.localhost
for config in "$BENCH_DIR"/sites/*/site_config.json; do
	if [[ -f "$config" ]]; then
		default_site="$(basename "$(dirname "$config")")"
		break
	fi
done
default_project="$(basename "$PROJECT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"

printf '\nS&S (Seat & Serve) setup\n=======================\n'
printf 'Use the same Docker Compose project name used to bootstrap this bench.\n'
project="$(ask 'Docker Compose project' "$default_project")"
site="$(ask 'Frappe site hostname' "$default_site")"
if [[ ! "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
	printf 'Use a lowercase Docker project name.\n' >&2; exit 2
fi
if [[ ! "$site" =~ ^[a-z0-9][a-z0-9.-]{2,120}$ || "$site" == *..* ]]; then
	printf 'Use a lowercase DNS hostname for the site.\n' >&2; exit 2
fi

if [[ -f "$BENCH_DIR/sites/$site/site_config.json" ]]; then
	mode=existing
else
	mode=new
fi
if [[ "$mode" == new ]]; then
	printf 'Site %s does not exist. It will be created with ERPNext, HRMS and S&S (Seat & Serve).\n' "$site"
fi

install_js=0
build_js=0
if ask_yes 'Install/update frontend dependencies?' Y; then install_js=1; fi
if ask_yes 'Build register, kitchen, kiosk and menu assets?' Y; then build_js=1; fi

printf '\nPlan: start Docker, %s site %s, install missing apps, migrate' "$mode" "$site"
if [[ "$install_js" == 1 ]]; then printf ', install frontend dependencies'; fi
if [[ "$build_js" == 1 ]]; then printf ', build assets'; fi
printf '.\n'
if [[ "$DRY_RUN" == 1 ]]; then
	printf 'Dry run only. No containers, site data or files were changed.\n'
	exit 0
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
	printf 'Docker Desktop/Engine with Compose must be installed and running.\n' >&2
	exit 1
fi
if ! ask_yes 'Run this setup now?' Y; then
	printf 'Setup cancelled.\n'
	exit 0
fi

db_password=''
admin_password=''
if [[ "$mode" == new ]]; then
	read -r -s -p 'MariaDB root password: ' db_password; printf '\n'
	read -r -s -p 'New site Administrator password: ' admin_password; printf '\n'
	if [[ -z "$db_password" || -z "$admin_password" ]]; then
		printf 'Both passwords are required to create a site.\n' >&2; exit 2
	fi
fi

compose up -d
compose exec -T frappe test -f "$CONTAINER_APP/table_remote_till/hooks.py"
if [[ "$mode" == new ]]; then
	printf 'Waiting for MariaDB to finish starting...\n'
	db_ready=0
	for ((attempt = 0; attempt < 60; attempt++)); do
		if compose exec -T mariadb healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then
			db_ready=1
			break
		fi
		sleep 2
	done
	if [[ "$db_ready" != 1 ]]; then
		printf 'MariaDB did not become ready. Check Docker Compose logs for the mariadb service.\n' >&2
		exit 1
	fi
	# provision_site.py refuses to overwrite an existing site and hides credentials on failure.
	compose exec -T -w "$CONTAINER_APP" \
		-e "TRT_DB_ROOT_PASSWORD=$db_password" \
		-e "TRT_SITE_ADMIN_PASSWORD=$admin_password" \
		-e TRT_DB_HOST=mariadb frappe \
		python tools/provision_site.py "$site" --db-host mariadb
else
	installed="$(compose exec -T -w "$CONTAINER_BENCH" frappe bench --site "$site" list-apps)"
	for app in erpnext hrms table_remote_till; do
		if ! grep -Eq "^[[:space:]]*$app[[:space:]]" <<< "$installed"; then
			compose exec -T -w "$CONTAINER_BENCH" frappe bench --site "$site" install-app "$app"
		fi
	done
fi
unset db_password admin_password

if [[ "$install_js" == 1 ]]; then
	for frontend in till kitchen kiosk menu; do
		compose exec -T -w "$CONTAINER_APP/$frontend" frappe yarn install --force --frozen-lockfile
	done
fi
if [[ "$build_js" == 1 ]]; then
	compose exec -T -w "$CONTAINER_APP" frappe yarn build
	compose exec -T -w "$CONTAINER_BENCH" frappe bench build --app table_remote_till
fi
compose exec -T -w "$CONTAINER_BENCH" frappe bench --site "$site" migrate

printf '\nSetup complete. Open http://%s:8000/onboarding, then /till, /kitchen or /reservations.\n' "$site"
