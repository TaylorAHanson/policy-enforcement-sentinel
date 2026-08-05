def test_get_readme(client):
    response = client.get("/api/v1/readme/")
    assert response.status_code == 200
    assert "content" in response.json()
