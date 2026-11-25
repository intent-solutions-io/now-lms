#!/bin/bash
# Exercise the real deployment smoke against synthetic responses, without Docker
# or network access. The company credential must not mask private course text.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fixture="$(mktemp -d)"
trap 'rm -rf "${fixture}"' EXIT
mkdir -p "${fixture}/scripts" "${fixture}/bin"
cp -f "${repo_root}/scripts/deploy-smoke.sh" "${fixture}/scripts/"
cat > "${fixture}/bin/git" <<'STUB'
#!/bin/bash
case "$*" in
  *--abbrev-ref*) echo main ;;
  *--verify*) exit 1 ;;
  *) echo fixture-commit ;;
esac
STUB
cat > "${fixture}/bin/docker" <<'STUB'
#!/bin/bash
case "$*" in
  *BUILD_SHA*) echo fixture-commit ;;
  *) echo healthy ;;
esac
STUB
cat > "${fixture}/bin/curl" <<'STUB'
#!/bin/bash
case "${!#}" in
  https://learn.intentsolutions.io*)
    if [[ "${!#}" == *\?* ]]; then echo 'unexpected query bypass' >&2; exit 1; fi
    if [ "${!#}" = "https://learn.intentsolutions.io/home" ]; then
      printf '%s' "${HOME_REDIRECT:-302 https://learn.intentsolutions.io/}"
      exit 0
    fi
    if [ "${!#}" = "https://learn.intentsolutions.io${STALE_PUBLIC_PATH:-missing}" ]; then
      echo '<meta name="intent-learn-release" content="old-release" />'
    else
      echo '<meta name="intent-learn-release" content="fixture-commit" />'
    fi
    ;;
  */course/explore) printf '%s' "$TEST_TEASER" ;;
  */request-access) echo '<form class="isl-ra-form"><a href="mailto:support@example.invalid">Contact</a></form>' ;;
  */contact) echo 404 ;;
  */view) echo 302 ;;
  *) echo '<div class="isl-hero-copy embedded_badge"><a href="/request-access">Start</a></div>' ;;
esac
STUB
chmod +x "${fixture}/bin/"*
export PATH="${fixture}/bin:${PATH}"
badge="$(cat "${repo_root}/now_lms/templates/themes/intent_learn/partner_badge.j2")"
export TEST_TEASER
TEST_TEASER='<div class="isl-tracks-list">Practice tracks</div>'
bash "${fixture}/scripts/deploy-smoke.sh" >/dev/null
TEST_TEASER+="${badge}"
bash "${fixture}/scripts/deploy-smoke.sh" >/dev/null
for forbidden in 'Claude curriculum' 'Anthropic course' 'CCA-A' 'isl-course-grid'; do
  if TEST_TEASER="${TEST_TEASER}<p>${forbidden}</p>" bash "${fixture}/scripts/deploy-smoke.sh" >"${fixture}/result" 2>&1; then
    echo "FAIL: private marker ${forbidden} was accepted" >&2
    exit 1
  fi
  grep -q 'leaking course cards or vendor names' "${fixture}/result"
done
# The strip is not a blanket exemption: even a leak inside it must be rejected.
if TEST_TEASER="${TEST_TEASER/Built by/Anthropic curriculum}" bash "${fixture}/scripts/deploy-smoke.sh" >"${fixture}/result" 2>&1; then
  echo 'FAIL: vendor text inside the partner strip was accepted' >&2
  exit 1
fi
grep -q 'leaking course cards or vendor names' "${fixture}/result"
echo 'PASS: public teaser smoke (2 allowed responses, 5 rejected leaks)'

# An image/loopback check can pass while the public ingress still serves an old
# shared response. Every plain public entry path must reject that exact defect.
for path in / /course/explore /program/explore; do
  if STALE_PUBLIC_PATH="${path}" bash "${fixture}/scripts/deploy-smoke.sh" >"${fixture}/result" 2>&1; then
    echo "FAIL: stale public ${path} was accepted" >&2
    exit 1
  fi
  grep -Fq "public ${path} is not rendering release fixture-commit" "${fixture}/result"
done
echo 'PASS: stale public responses rejected on all three rendered URLs'

# /home is redirected to / by the ingress; anything else from it must fail.
for answer in '200 ' '301 https://learn.intentsolutions.io/' '302 https://example.invalid/'; do
  if HOME_REDIRECT="${answer}" bash "${fixture}/scripts/deploy-smoke.sh" >"${fixture}/result" 2>&1; then
    echo "FAIL: /home answer '${answer}' was accepted" >&2
    exit 1
  fi
  grep -Fq 'public /home should redirect to /' "${fixture}/result"
done
echo 'PASS: /home must 302 to / (3 wrong answers rejected)'
