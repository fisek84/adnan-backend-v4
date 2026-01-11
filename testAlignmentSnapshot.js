const assert = require('assert');

// Simulacija dohvaćanja alignment snapshot-a prije i poslije preporuke
function getAlignmentSnapshot(stage) {
    if (stage === 'before') {
        return 0.75; // Simuliraj alignment prije
    }
    return 0.85; // Simuliraj alignment nakon
}

// Simulacija izračuna delta_score
function calculateDeltaScore(alignmentBefore, alignmentAfter) {
    return parseFloat((alignmentAfter - alignmentBefore).toFixed(2)); // Zaokruži na 2 decimale
}

// Simulacija izračuna delta_risk
function calculateDeltaRisk(riskBefore, riskAfter) {
    return parseFloat((riskBefore - riskAfter).toFixed(2)); // Zaokruži na 2 decimale
}

// Simulacija pohrane podataka
let alignmentData = {};
function storeAlignmentData(decisionId, alignmentBefore, alignmentAfter) {
    alignmentData[decisionId] = { alignment_before: alignmentBefore, alignment_after: alignmentAfter };
}

// Simulacija pohrane rezultata
let outcomeResults = [];
function storeOutcome(decisionId, deltaScore, deltaRisk) {
    outcomeResults.push({
        decisionId: decisionId,
        delta_score: deltaScore,
        delta_risk: deltaRisk,
        timestamp: new Date()
    });
}

// Simulacija rasporeda pregleda (review)
function scheduleReview(decisionDate, intervalDays) {
    const reviewDate = new Date(decisionDate);
    reviewDate.setDate(reviewDate.getDate() + intervalDays); // Dodaj interval u dane
    return reviewDate;
}

// Testiranje
const decisionId = 'decision123';
const alignmentBefore = getAlignmentSnapshot('before');
const alignmentAfter = getAlignmentSnapshot('after');

// Pohrani podatke
storeAlignmentData(decisionId, alignmentBefore, alignmentAfter);

// Izračunaj delta_score i delta_risk
const deltaScore = calculateDeltaScore(alignmentBefore, alignmentAfter);
const deltaRisk = calculateDeltaRisk(0.3, 0.25); // Simuliraj promjenu rizika

// Pohrani rezultate
storeOutcome(decisionId, deltaScore, deltaRisk);

// Provjeri pohranjivanje podataka
assert.equal(alignmentData[decisionId].alignment_before, alignmentBefore, 'Alignment before does not match');
assert.equal(alignmentData[decisionId].alignment_after, alignmentAfter, 'Alignment after does not match');

// Provjeri pohranu rezultata
const storedOutcome = outcomeResults.find(result => result.decisionId === decisionId);
assert.equal(storedOutcome.delta_score, deltaScore, 'Stored delta_score does not match');
assert.equal(storedOutcome.delta_risk, deltaRisk, 'Stored delta_risk does not match');

console.log('Test passed successfully!');
