app.get('/health', (req, res) => res.send('ok'));
app.get('/metrics', (req, res) => res.send(''));
fetch('/health');
