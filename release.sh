#!/usr/bin/env bash
#
# release.sh — corta un release HACS de aux_lan.
#
# HACS sirve la integración desde GitHub Releases con tag semver. El tag DEBE
# coincidir con "version" en custom_components/aux_lan/manifest.json o HACS no
# detecta el update. Este script deriva el tag del manifest para que nunca se
# desincronicen, valida precondiciones y crea tag + GitHub Release.
#
# Reparto: este script (invocado por el usuario via `make release-aux-lan`) hace
# tag + push + gh release. El commit/merge a main lo hace el usuario ANTES. El
# Update en HACS + restart de HA lo hace el usuario DESPUÉS, en HA.
#
# Uso:
#   make release-aux-lan                 # notas autogeneradas por GitHub
#   make release-aux-lan NOTES="texto"   # notas propias
set -euo pipefail

cd "$(dirname "$0")"
MANIFEST="custom_components/aux_lan/manifest.json"
NOTES="${NOTES:-}"

red() { printf "\033[31m%s\033[0m\n" "$1"; }
grn() { printf "\033[32m%s\033[0m\n" "$1"; }
die() { red "✗ $1"; exit 1; }

command -v gh >/dev/null  || die "falta gh CLI"
[ -f "$MANIFEST" ]        || die "no encuentro $MANIFEST (¿corriendo desde el repo del component?)"

VERSION=$(grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' "$MANIFEST" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
[ -n "$VERSION" ] || die "no pude leer version semver del manifest"
TAG="v$VERSION"

# precondiciones
BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ]                || die "no estás en main (estás en '$BRANCH'). Mergeá tu branch a main primero."
[ -z "$(git status --porcelain)" ]    || die "working tree sucio. Commiteá/limpiá antes de releasear."

git fetch --tags --quiet origin
if git rev-parse "$TAG" >/dev/null 2>&1 || git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  die "el tag $TAG ya existe. ¿Olvidaste bumpear la version en $MANIFEST?"
fi

# confirmar
echo
echo "  manifest version : $VERSION"
echo "  tag a crear      : $TAG"
echo "  commit           : $(git rev-parse --short HEAD) — $(git log -1 --pretty=%s)"
echo "  notas            : ${NOTES:-<autogeneradas por GitHub>}"
echo
read -rp "Crear release $TAG y pushear? [y/N] " ans
[ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "abortado."

# ejecutar
git tag "$TAG"
git push origin main
git push origin "$TAG"
if [ -n "$NOTES" ]; then
  gh release create "$TAG" --title "$TAG" --notes "$NOTES"
else
  gh release create "$TAG" --title "$TAG" --generate-notes
fi

grn "✓ release $TAG publicado."
echo "  Ahora en HA: HACS → Integrations → AUX LAN → Update → ha core restart"
