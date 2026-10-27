import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from cartridges.utils import quiver_catalog
from cartridges.utils.download import ResponseTooLargeError
from cartridges.utils.quiver_catalog import QuiverEnrichment, enrich_entry


def _response(payload, status_code=200):
    """Uma `requests.Response` de verdade, com corpo JSON."""
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.quiverlauncher.com/api/v1/apps"
    response.encoding = "utf-8"
    if isinstance(payload, bytes):
        response._content = payload  # pylint: disable=protected-access
    elif isinstance(payload, str):
        response._content = payload.encode("utf-8")
    else:
        response._content = json.dumps(payload).encode("utf-8")
    return response


def _item(
    slug="example-app",
    name="Example App",
    project_name="Example Project",
    artwork="https://cdn.example/icon.png",
    library_art=None,
):
    """Um item do ``GET /apps``."""
    if library_art is None:
        library_art = {
            "capsule": "https://cdn.example/capsule.png",
            "header": "https://cdn.example/header.png",
            "hero": "https://cdn.example/hero.png",
            "logo": "https://cdn.example/logo.png",
        }
    return {
        "id": "k179cwcjmbeves16st2tehqsr98f4z51",
        "slug": slug,
        "name": name,
        "projectName": project_name,
        "description": "A description",
        "developer": {"key": "studio", "name": "Studio"},
        "artwork": artwork,
        "libraryArt": library_art,
        "tags": ["port", "linux"],
        "lastReleaseVersion": "1.2.3",
        "verified": {"version": "1.2.3", "rolling": False},
    }


def _detail(entry=None, repository="owner/example-project"):
    """Uma resposta de ``GET /apps/{slug}``."""
    return {
        "entry": entry if entry is not None else _item(),
        "project": {"provider": "github", "repository": repository},
    }


class _FakeApi:
    """Roteia as URLs do catálogo para respostas preparadas."""

    def __init__(self):
        self.calls = []
        self.handlers = []

    def on(self, marker, response=None, error=None):
        self.handlers.append((marker, response, error))
        return self

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        for marker, response, error in self.handlers:
            if marker in url:
                if error is not None:
                    raise error
                return response(url) if callable(response) else response
        if "search=" in url:
            # Uma busca sem resultado: a página vazia do catálogo.
            return _response({"items": [], "nextCursor": None, "isDone": True})
        raise AssertionError(f"URL inesperada: {url}")

    @property
    def searches(self):
        return [url for url in self.calls if "search=" in url]


class QuiverCatalogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "quiver_catalog.json"
        self.api = _FakeApi()

    def _enrich(self, entry, api=None, **kwargs):
        """Chama `enrich_entry` com a rede falsa no lugar."""
        api = api or self.api
        with patch.object(quiver_catalog, "get_capped", side_effect=api):
            return enrich_entry(entry, cache_path=self.cache, **kwargs)

    def test_catalog_entry_id_casa_com_o_id_da_busca(self):
        self.api.on("search=example-project", _response({"items": [_item()]}))

        result = self._enrich(
            {
                "catalogEntryId": "k179cwcjmbeves16st2tehqsr98f4z51",
                "name": "Example App",
                "repository": "owner/example-project",
            }
        )

        self.assertEqual(
            result,
            QuiverEnrichment(
                cover_url="https://cdn.example/header.png",
                description="A description",
                version="1.2.3",
                developer="Studio",
                tags=["port", "linux"],
            ),
        )
        # Uma requisição só: a busca, sem o `GET /apps/{id}` que responderia
        # 404 e sem conferir o detalhe de um app já identificado.
        self.assertEqual(len(self.api.calls), 1)
        self.assertIn("search=", self.api.calls[0])

    def test_catalog_entry_id_vence_o_repositorio_da_busca(self):
        # A entrada aponta um app do catálogo e o repositório dela é outro: o
        # id é a identidade exata, então nada precisa ser confirmado.
        self.api.on("search=example-project", _response({"items": [_item()]}))

        result = self._enrich(
            {
                "catalogEntryId": "k179cwcjmbeves16st2tehqsr98f4z51",
                "name": "Outro Nome",
                "repository": "owner/example-project",
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.developer, "Studio")
        self.assertEqual(len(self.api.calls), 1)
        self.assertNotIn("/apps/example-app", self.api.calls)

    def test_slug_escrito_a_mao_resolve_no_detalhe(self):
        # Sem repositório nem nome não há busca: um `apps.json` escrito à mão
        # que guardou o slug no lugar do id ainda resolve.
        self.api.on("/apps/example-app", _response(_detail()))

        result = self._enrich({"catalogEntryId": "example-app"})

        self.assertIsNotNone(result)
        self.assertEqual(len(self.api.calls), 1)
        self.assertIn("/apps/example-app", self.api.calls[0])

    def test_busca_por_repositorio_confirma_no_detalhe(self):
        self.api.on("search=example-project", _response({"items": [_item()]}))
        self.api.on("/apps/example-app", _response(_detail()))

        result = self._enrich(
            {
                "catalogEntryId": "k179",
                "name": "Example App",
                "repository": "owner/example-project",
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.cover_url, "https://cdn.example/header.png")
        self.assertEqual(len(self.api.searches), 1)

    def test_busca_por_repositorio_exige_repositorio_igual(self):
        # O candidato tem outro repositório e outro nome: nada casa.
        self.api.on("/apps/k179", _response({"error": {"code": "NOT_FOUND"}}, 404))
        self.api.on(
            "search=example-project",
            _response({"items": [_item(name="Outro App")]}),
        )
        self.api.on(
            "/apps/example-app", _response(_detail(repository="outro/dono"))
        )

        result = self._enrich(
            {
                "catalogEntryId": "k179",
                "name": "Nome Diferente",
                "repository": "owner/example-project",
            }
        )

        self.assertIsNone(result)

    def test_nome_exato_serve_quando_o_repositorio_nao_casa(self):
        # O nome da entrada é igual ao do candidato: a regra do nome vale
        # mesmo com outro repositório, e o app continua sendo o mesmo.
        self.api.on(
            "search=example-project",
            _response({"items": [_item(name="Example App")]}),
        )
        self.api.on(
            "/apps/example-app", _response(_detail(repository="outro/dono"))
        )

        result = self._enrich(
            {
                "catalogEntryId": "k179",
                "name": "Example App",
                "repository": "owner/example-project",
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.version, "1.2.3")

    def test_busca_por_nome_aceita_o_unico_candidato_com_o_mesmo_nome(self):
        self.api.on(
            "search=Example+App",
            _response({"items": [_item(name="Example App"), _item(slug="outro", name="Outro App")]}),
        )

        result = self._enrich({"name": "Example App"})

        self.assertIsNotNone(result)
        self.assertEqual(result.developer, "Studio")
        self.assertEqual(result.tags, ["port", "linux"])

    def test_resultados_ambiguos_viram_none(self):
        self.api.on(
            "search=Example+App",
            _response(
                {
                    "items": [
                        _item(slug="a", name="Example App"),
                        _item(slug="b", name="example app"),
                    ]
                }
            ),
        )

        self.assertIsNone(self._enrich({"name": "Example App"}))

    def test_mesmo_repositorio_desempata_pelo_nome(self):
        # Dois builds do mesmo repositório: o nome do app decide.
        self.api.on(
            "search=example-project",
            _response(
                {
                    "items": [
                        _item(slug="linux"),
                        _item(slug="android", name="Example App [Android]"),
                    ]
                }
            ),
        )
        self.api.on("/apps/linux", _response(_detail()))
        self.api.on(
            "/apps/android",
            _response(_detail(entry=_item(name="Example App [Android]"))),
        )

        resultado = self._enrich(
            {"name": "Example App", "repository": "owner/example-project"}
        )

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.version, "1.2.3")

    def test_repositorio_ambiguo_sem_nome_vira_none(self):
        self.api.on(
            "search=example-project",
            _response(
                {
                    "items": [
                        _item(slug="linux"),
                        _item(slug="android", name="Example App [Android]"),
                    ]
                }
            ),
        )
        self.api.on("/apps/linux", _response(_detail()))
        self.api.on(
            "/apps/android",
            _response(_detail(entry=_item(name="Example App [Android]"))),
        )

        resultado = self._enrich({"repository": "owner/example-project"})

        self.assertIsNone(resultado)

    def test_o_candidato_mais_parecido_e_conferido_primeiro(self):
        # "Example Project" casa exatamente; "Example Project [Android]" só
        # contém. O detalhe é gasto no candidato exato antes do outro.
        self.api.on(
            "search=example-project",
            _response(
                {
                    "items": [
                        _item(slug="android", name="Android", project_name="Example Project [Android]"),
                        _item(slug="linux", name="Linux", project_name="Example Project"),
                    ]
                }
            ),
        )
        self.api.on("/apps/linux", _response(_detail()))
        self.api.on("/apps/android", _response(_detail()))

        self._enrich({"repository": "owner/example-project"})

        detalhes = [url for url in self.api.calls if "/apps/" in url and "search=" not in url]
        self.assertTrue(detalhes[0].endswith("/apps/linux"))

    def test_o_numero_de_consultas_ao_detalhe_e_limitado(self):
        candidatos = [
            _item(slug=f"candido{indice}", name=f"Candidato {indice}", project_name="Example Project")
            for indice in range(6)
        ]
        self.api.on("search=example-project", _response({"items": candidatos}))
        self.api.on("/apps/", _response(_detail()))

        self._enrich({"repository": "owner/example-project"})

        detalhes = [url for url in self.api.calls if "/apps/" in url and "search=" not in url]
        self.assertLessEqual(len(detalhes), quiver_catalog._MAX_DETAIL_PROBES)

    def test_sem_identidade_nao_faz_requisicao(self):
        self.assertIsNone(self._enrich({"appIconUrl": "https://cdn.example/i.png"}))
        self.assertEqual(self.api.calls, [])

    def test_erro_de_rede_serve_o_cache_velho(self):
        self.api.on("/apps/k179", _response(_detail()))
        primeiro = self._enrich(
            {"catalogEntryId": "k179"}, now=1000.0
        )
        self.assertIsNotNone(primeiro)

        offline = _FakeApi().on(
            "/apps/k179", error=requests.RequestException("sem rede")
        )
        segundo = self._enrich(
            {"catalogEntryId": "k179"}, api=offline, now=1000.0 + quiver_catalog.CACHE_TTL + 1
        )

        self.assertEqual(segundo, primeiro)

    def test_erro_de_rede_sem_cache_vira_none(self):
        offline = _FakeApi().on(
            "/apps/k179", error=requests.RequestException("sem rede")
        )
        self.assertIsNone(self._enrich({"catalogEntryId": "k179"}, api=offline))

    def test_json_invalido_vira_none(self):
        self.api.on("/apps/k179", _response(b"{isto nao e json"))

        self.assertIsNone(self._enrich({"catalogEntryId": "k179"}))

    def test_json_invalido_serve_o_cache_velho(self):
        self.api.on("/apps/k179", _response(_detail()))
        self._enrich({"catalogEntryId": "k179"}, now=1000.0)

        quebrado = _FakeApi().on("/apps/k179", _response(b"{isto nao e json"))
        resultado = self._enrich(
            {"catalogEntryId": "k179"},
            api=quebrado,
            now=1000.0 + quiver_catalog.CACHE_TTL + 1,
        )

        self.assertIsNotNone(resultado)
        self.assertEqual(resultado.version, "1.2.3")

    def test_resposta_grande_demais_vira_none(self):
        grande = _FakeApi().on(
            "/apps/k179", error=ResponseTooLargeError("body exceeded")
        )
        self.assertIsNone(self._enrich({"catalogEntryId": "k179"}, api=grande))

    def test_resposta_grande_demais_serve_o_cache_velho(self):
        self.api.on("/apps/k179", _response(_detail()))
        self._enrich({"catalogEntryId": "k179"}, now=1000.0)

        grande = _FakeApi().on(
            "/apps/k179", error=ResponseTooLargeError("body exceeded")
        )
        resultado = self._enrich(
            {"catalogEntryId": "k179"},
            api=grande,
            now=1000.0 + quiver_catalog.CACHE_TTL + 1,
        )

        self.assertIsNotNone(resultado)

    def test_cache_fresco_nao_toca_a_rede(self):
        self.api.on("/apps/k179", _response(_detail()))
        self._enrich({"catalogEntryId": "k179"}, now=1000.0)
        self.assertEqual(len(self.api.calls), 1)

        self._enrich(
            {"catalogEntryId": "k179"},
            now=1000.0 + quiver_catalog.CACHE_TTL - 1,
        )
        self.assertEqual(len(self.api.calls), 1)

    def test_ttl_vencido_busca_de_novo(self):
        self.api.on("/apps/k179", _response(_detail()))
        self._enrich({"catalogEntryId": "k179"}, now=1000.0)

        self._enrich(
            {"catalogEntryId": "k179"},
            now=1000.0 + quiver_catalog.CACHE_TTL + 1,
        )
        self.assertEqual(len(self.api.calls), 2)

    def test_cache_foi_gravado_com_versao_e_horario(self):
        self.api.on("/apps/k179", _response(_detail()))
        self._enrich({"catalogEntryId": "k179"}, now=1000.0)

        payload = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], quiver_catalog.CACHE_VERSION)
        registro = payload["entries"]["id:k179"]
        self.assertTrue(registro["found"])
        self.assertEqual(registro["fetched_at"], 1000.0)
        self.assertEqual(registro["enrichment"]["version"], "1.2.3")

    def test_somente_esquema_http_e_https_e_aceito_na_capa(self):
        self.api.on(
            "/apps/k179",
            _response(
                _detail(
                    entry=_item(
                        artwork="javascript:alert(1)",
                        library_art={
                            "capsule": "file:///etc/passwd",
                            "header": "javascript:alert(1)",
                        },
                    )
                )
            ),
        )

        resultado = self._enrich({"catalogEntryId": "k179"})
        self.assertIsNone(resultado.cover_url)

    def test_capa_usa_o_header_e_depois_o_capsule(self):
        self.api.on(
            "/apps/k179",
            _response(
                _detail(
                    entry=_item(
                        library_art={
                            "capsule": "https://cdn.example/capsule.png",
                            "header": "https://cdn.example/header.png",
                        }
                    )
                )
            ),
        )
        resultado = self._enrich({"catalogEntryId": "k179"})
        self.assertEqual(resultado.cover_url, "https://cdn.example/header.png")

        self.api.on(
            "/apps/k2",
            _response(
                _detail(
                    entry=_item(
                        library_art={"capsule": "https://cdn.example/capsule.png"}
                    )
                )
            ),
        )
        resultado = self._enrich({"catalogEntryId": "k2"})
        self.assertEqual(resultado.cover_url, "https://cdn.example/capsule.png")

    def test_capa_cai_para_a_arte_quando_a_capa_do_catalogo_falta(self):
        self.api.on(
            "/apps/k179",
            _response(_detail(entry=_item(library_art={}))),
        )
        resultado = self._enrich({"catalogEntryId": "k179"})
        self.assertEqual(resultado.cover_url, "https://cdn.example/icon.png")

    def test_falha_de_conexao_tenta_o_host_de_reserva(self):
        def por_url(url):
            if "famous-wildebeest" in url:
                return _response(_detail())
            raise requests.ConnectionError("handshake falhou")

        api = _FakeApi().on("/apps/k179", response=por_url)
        resultado = self._enrich({"catalogEntryId": "k179"}, api=api)

        self.assertIsNotNone(resultado)
        self.assertEqual(len(api.calls), 2)
        self.assertIn("famous-wildebeest", api.calls[1])

    def test_timeout_nao_tenta_o_host_de_reserva(self):
        api = _FakeApi().on(
            "/apps/k179", error=requests.Timeout("demorou")
        )
        self.assertIsNone(self._enrich({"catalogEntryId": "k179"}, api=api))
        self.assertEqual(len(api.calls), 1)


if __name__ == "__main__":
    unittest.main()
