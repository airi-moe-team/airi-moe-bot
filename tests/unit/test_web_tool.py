from airi.domain.web_tool import (
    SearchRequest,
    note_years,
    parse_search_request,
    render_search_block,
)
from airi.ports.web_search import WebResult, WebSearchNotes


def test_parse_search_request_accepts_normalized_or_openai_calls():
    request = parse_search_request([
        {
            "id": "call-1",
            "function": {
                "name": "buscar_web",
                "arguments": '{"query":"  precio bitcoin  ","motivo":"me dio curiosidad"}',
            },
        }
    ])
    assert request == SearchRequest("precio bitcoin", "me dio curiosidad")


def test_parse_search_request_ignores_unknown_or_invalid_calls():
    assert parse_search_request([
        {"name": "other", "arguments": {"query": "x"}},
        {"name": "buscar_web", "arguments": "not-json"},
    ]) is None


def test_render_search_block_has_notes_but_no_urls_or_fixed_reply_examples():
    notes = WebSearchNotes((WebResult(
        "Precios de entradas", "Entrada general cuesta 90 euros. https://example.test"
    ),))
    block = render_search_block(
        SearchRequest("precio entradas", "me picó la curiosidad"), notes
    )
    assert "me picó la curiosidad" in block
    assert "90 euros" in block
    assert "dato concreto y pertinente" in block
    assert "al menos uno" in block
    assert "no fuerces datos" in block
    assert "https://" not in block
    assert "Fuente 1" not in block
    assert "según las fuentes" in block
    assert '"lo acabo de mirar"' not in block


def test_note_years_reports_multiple_years_as_neutral_metadata():
    notes = WebSearchNotes((
        WebResult("Estreno 2012", "Se estrenó en 2012."),
        WebResult("Otra fecha", "La película llegó en 2013."),
    ))
    assert note_years(notes) == ("2012", "2013")
    block = render_search_block(SearchRequest("estreno", "dudé"), notes)
    assert "Años mencionados en las notas: 2012, 2013" in block


def test_empty_search_block_is_descriptive_not_canonical_dialogue():
    block = render_search_block(SearchRequest("query"), None, failed=True)
    assert "La búsqueda se ejecutó" in block
    assert "no devolvió notas útiles" in block
    assert "No digas que careces de acceso a internet" in block
    assert "No he encontrado información fiable" not in block
