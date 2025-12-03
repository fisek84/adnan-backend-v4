console.log("✅ LOADING server.js iz tačne verzije");

const express = require('express');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// OBAVEZNO za parsiranje JSON tijela
app.use(express.json());

// --- Home ruta za test ---
app.get('/', (req, res) => {
  res.send('Server radi!');
});

app.get('/test-post-simulacija', (req, res) => {
  const fakeBody = { title: 'Simulacija iz browsera' };
  console.log('🔥 Simulirani POST:', fakeBody);
  res.status(200).json({
    message: 'Simulacija prošla',
    data: fakeBody
  });
});


// --- POST ruta za projekte ---
app.post('/api/projects', (req, res) => {
  const data = req.body;
  console.log('Primljen projekat:', data);
  res.status(201).json({
    message: 'Projekat kreiran',
    data: data
  });
});

// Pokretanje servera
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
