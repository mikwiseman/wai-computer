"use strict";
const DB = "/school-data/bouquet";
const archetypes = {
    "wild-tenderness": {
        key: "wild-tenderness",
        name: "Wild tenderness",
        preview: "Softness with character",
        portrait: "Warm, free and authentic. You make it easier for people to be themselves.",
        signals: [
            "Lively softness",
            "Freedom without chaos"
        ],
        image: "assets/wild-tenderness-field.webp",
        imageAlt: "A wild bouquet of cosmos, daisies and sweet peas in the breeze",
        gallery: [
            "assets/wild-tenderness-field.webp",
            "assets/wild-tenderness-herbarium.webp",
            "assets/wild-tenderness.webp"
        ],
        prototype: { softness: 88, energy: 54, mystery: 42, structure: 22 },
        formula: "Cosmos + sweet pea + daisy",
        why: "Loose lines, delicate petals, as if the flowers were picked along the way.",
        flowers: [
            { role: "Leading note", name: "Cosmos" },
            { role: "Soft layer", name: "Sweet pea" },
            { role: "Light accent", name: "Daisy" }
        ],
        palette: ["#f37b73", "#c5b2e7", "#f6f2e8", "#6f8a46"],
        florist: "Long stems, airy asymmetry and loose wrapping.",
        hint: "If you ever want to give me flowers, choose a bouquet that looks alive and a little windswept.",
        story: { bg: "#e9e7f0", ink: "#25212c", accent: "#3446d3" }
    },
    "quiet-depth": {
        key: "quiet-depth",
        name: "Quiet depth",
        preview: "Silence full of meaning",
        portrait: "You speak softly but see deeply, and remember what matters.",
        signals: [
            "Quiet strength",
            "An eye for detail"
        ],
        image: "assets/quiet-depth-rain.webp",
        imageAlt: "Plum calla lilies and white lisianthus by a rainy night window",
        gallery: [
            "assets/quiet-depth-rain.webp",
            "assets/quiet-depth-water.webp",
            "assets/quiet-depth.webp"
        ],
        prototype: { softness: 66, energy: 22, mystery: 92, structure: 66 },
        formula: "Plum calla lily + lisianthus + delphinium",
        why: "A clean silhouette, dark depth and light pauses.",
        flowers: [
            { role: "Silhouette", name: "Plum calla lily" },
            { role: "Air", name: "White lisianthus" },
            { role: "Depth", name: "Blue delphinium" }
        ],
        palette: ["#3f183d", "#17294f", "#f0eadf", "#696d3b"],
        florist: "A tall shape, dark center, light pauses and minimal greenery.",
        hint: "I like bouquets where the shape catches your eye first, then the details draw you in.",
        story: { bg: "#d7d3dc", ink: "#251b2a", accent: "#54244f" }
    },
    "solar-spark": {
        key: "solar-spark",
        name: "Sunlit impulse",
        preview: "Energy that catches on",
        portrait: "You turn an ordinary day into an event and get people moving.",
        signals: [
            "Bright energy",
            "Spontaneous rhythm"
        ],
        image: "assets/solar-spark-sky.webp",
        imageAlt: "A sunny bouquet of ranunculus, tulips and mimosa against the sky",
        gallery: [
            "assets/solar-spark-sky.webp",
            "assets/solar-spark-picnic.webp",
            "assets/solar-spark.webp"
        ],
        prototype: { softness: 48, energy: 94, mystery: 20, structure: 28 },
        formula: "Ranunculus + tulip + mimosa",
        why: "Warm color, movement and mimosa that seems to scatter light.",
        flowers: [
            { role: "Energy", name: "Orange ranunculus" },
            { role: "Movement", name: "Yellow tulip" },
            { role: "Sparks", name: "Mimosa" }
        ],
        palette: ["#f47b20", "#ffd328", "#f7f2e8", "#5f7d34"],
        florist: "A bright warm center, long tulips and no kraft paper.",
        hint: "Choose flowers for me that look as though something wonderful is about to happen.",
        story: { bg: "#f5e9bd", ink: "#332516", accent: "#d55b18" }
    },
    "velvet-boldness": {
        key: "velvet-boldness",
        name: "Velvet boldness",
        preview: "A strong presence",
        portrait: "You take up your space: expressive, direct and memorable without explanation.",
        signals: [
            "A strong presence",
            "Grounded warmth"
        ],
        image: "assets/velvet-boldness-night.webp",
        imageAlt: "Burgundy peonies and dahlias in a dark theater corridor",
        gallery: [
            "assets/velvet-boldness-night.webp",
            "assets/velvet-boldness-chrome.webp",
            "assets/velvet-boldness.webp"
        ],
        prototype: { softness: 32, energy: 78, mystery: 86, structure: 56 },
        formula: "Burgundy peony + dahlia + anthurium",
        why: "Rich volume, wine colors and one bold gesture.",
        flowers: [
            { role: "Leading emotion", name: "Burgundy peony" },
            { role: "Rhythm", name: "Wine dahlia" },
            { role: "Gesture", name: "Pink anthurium" }
        ],
        palette: ["#66132f", "#a92f54", "#e2a4ad", "#2f2930"],
        florist: "Rich volume, a wine palette, a striking anthurium and no glitter.",
        hint: "I want a bouquet that makes no apologies for being beautiful and noticeable.",
        story: { bg: "#d9c8d6", ink: "#321526", accent: "#7f1f43" }
    },
    "air-muse": {
        key: "air-muse",
        name: "Airy muse",
        preview: "Curiosity and lightness",
        portrait: "Curiosity guides you. You change perspective and leave more room to breathe.",
        signals: [
            "Lightness of thought",
            "Lively curiosity"
        ],
        image: "assets/air-muse-coast.webp",
        imageAlt: "An airy blue bouquet of delphinium and sweet peas by the sea",
        gallery: [
            "assets/air-muse-coast.webp",
            "assets/air-muse-glass.webp",
            "assets/air-muse.webp"
        ],
        prototype: { softness: 58, energy: 66, mystery: 34, structure: 44 },
        formula: "Delphinium + sweet pea + eucalyptus",
        why: "Tall lines, cool light and plenty of space between the stems.",
        flowers: [
            { role: "Height", name: "Light blue delphinium" },
            { role: "Lightness", name: "White sweet pea" },
            { role: "Line", name: "Silver eucalyptus" }
        ],
        palette: ["#83b8e9", "#f3f1ea", "#9aa9a1", "#2d4fbe"],
        florist: "A cool palette, a tall line and no round ball of flowers.",
        hint: "I like bouquets with air, blue tones and a sense of open space.",
        story: { bg: "#dbe8f1", ink: "#1f2a35", accent: "#3154b8" }
    },
    "precise-elegance": {
        key: "precise-elegance",
        name: "Precise elegance",
        preview: "Calm composure",
        portrait: "You notice what is unnecessary at a glance and choose precision that feels effortless.",
        signals: [
            "Clean form",
            "Quiet discernment"
        ],
        image: "assets/precise-elegance-architecture.webp",
        imageAlt: "An architectural arrangement of white orchids and blue delphinium",
        gallery: [
            "assets/precise-elegance-architecture.webp",
            "assets/precise-elegance-overhead.webp",
            "assets/precise-elegance.webp"
        ],
        prototype: { softness: 44, energy: 36, mystery: 58, structure: 94 },
        formula: "White orchid + cream rose + blue accent",
        why: "White architecture, one cobalt accent and no accidental details.",
        flowers: [
            { role: "Architecture", name: "White orchid" },
            { role: "Warmth", name: "Cream rose" },
            { role: "Accent", name: "Blue delphinium" }
        ],
        palette: ["#f4f1e9", "#d8d3c8", "#173fa7", "#294331"],
        florist: "A white base, one cobalt accent and no extra decoration.",
        hint: "Choose a bouquet for me with a clean form and one unexpected blue accent.",
        story: { bg: "#ecebf0", ink: "#1e2029", accent: "#2746bb" }
    }
};
const questions = [
    {
        note: "Imagine your plans were cancelled",
        title: "You suddenly have a free evening. What sounds best?",
        options: [
            { id: "home", title: "Go home and exhale", description: "Music, a shower, good food and do-not-disturb mode.", traits: { softness: 72, energy: 18, mystery: 58, structure: 62 } },
            { id: "city", title: "Head somewhere without a plan", description: "Step outside first. Figure out the route along the way.", traits: { softness: 44, energy: 88, mystery: 36, structure: 18 } },
            { id: "talk", title: "Invite one close friend", description: "Talk for hours and finally discuss everything that matters.", traits: { softness: 90, energy: 34, mystery: 68, structure: 42 } },
            { id: "gallery", title: "Go and see something beautiful", description: "An exhibition, a bookshop, a photo walk or a new neighborhood.", traits: { softness: 56, energy: 52, mystery: 72, structure: 76 } }
        ]
    },
    {
        note: "Do not analyze. Let your eyes choose",
        title: "Which arrangement draws you in?",
        options: [
            { id: "wild", title: "Alive and windswept", description: "Lots of air and slender stems, as if the flowers grew there themselves.", art: "assets/wild-tenderness.webp", traits: { softness: 90, energy: 54, mystery: 38, structure: 18 } },
            { id: "solar", title: "Rich and sunny", description: "Color, rhythm and the feeling that everything is just beginning.", art: "assets/solar-spark.webp", traits: { softness: 50, energy: 96, mystery: 18, structure: 28 } },
            { id: "velvet", title: "Dark and dramatic", description: "Deep shades, large shapes and a bold gesture.", art: "assets/velvet-boldness.webp", traits: { softness: 28, energy: 78, mystery: 92, structure: 58 } },
            { id: "precise", title: "Clean and graphic", description: "A white base, one accent and nothing extra.", art: "assets/precise-elegance.webp", traits: { softness: 42, energy: 34, mystery: 56, structure: 96 } }
        ]
    },
    {
        note: "Which compliment stays with you?",
        title: "Which of these feels most like you?",
        options: [
            { id: "easy", title: "“You make things feel lighter”", description: "You ease tension and help things move again.", traits: { softness: 72, energy: 70, mystery: 18, structure: 34 } },
            { id: "notice", title: "“You notice what others miss”", description: "You catch details, tones of voice and hidden connections.", traits: { softness: 58, energy: 28, mystery: 92, structure: 62 } },
            { id: "want", title: "“You know exactly what you want”", description: "You have an inner compass that is hard to unsettle.", traits: { softness: 30, energy: 72, mystery: 54, structure: 96 } },
            { id: "safe", title: "“I can be myself around you”", description: "You create space without judgment or pretense.", traits: { softness: 96, energy: 32, mystery: 46, structure: 28 } }
        ]
    },
    {
        note: "Think of your recent messages",
        title: "How do you usually text?",
        options: [
            { id: "voice", title: "Three-minute voice messages", description: "The thought takes shape as you record.", traits: { softness: 56, energy: 96, mystery: 16, structure: 18 } },
            { id: "exact", title: "One precise message", description: "Think first, then say it without anything extra.", traits: { softness: 44, energy: 24, mystery: 62, structure: 96 } },
            { id: "meme", title: "A meme, a reaction, another meme", description: "Why explain when the perfect picture says it all?", traits: { softness: 48, energy: 78, mystery: 32, structure: 24 } },
            { id: "return", title: "Disappear, then return with a real answer", description: "You need a pause to say exactly what you feel.", traits: { softness: 68, energy: 18, mystery: 94, structure: 54 } }
        ]
    },
    {
        note: "Color says something about character too",
        title: "Which palette could be yours?",
        options: [
            { id: "wine", title: "Cherry, dusty rose, lilac", description: "Deep, expressive and a little cinematic.", swatches: ["#70152f", "#d89aa7", "#b8a4d7"], traits: { softness: 44, energy: 74, mystery: 88, structure: 54 } },
            { id: "cobalt", title: "Cobalt, white, cool green", description: "Clean, composed and with one strong accent.", swatches: ["#173fa7", "#f2f0e8", "#334c3d"], traits: { softness: 40, energy: 42, mystery: 52, structure: 96 } },
            { id: "citrus", title: "Apricot, yellow, fresh green", description: "Warm energy with no holding back.", swatches: ["#ef7925", "#f4cf24", "#65833d"], traits: { softness: 62, energy: 96, mystery: 18, structure: 26 } },
            { id: "sky", title: "Sky blue, cream, sage", description: "Light, air and a calm rhythm.", swatches: ["#91bce4", "#f0eee7", "#93a58f"], traits: { softness: 82, energy: 42, mystery: 42, structure: 34 } }
        ]
    },
    {
        note: "It is the thought, not the price",
        title: "Which gestures move you most?",
        options: [
            { id: "bold", title: "Big and unmistakable", description: "When someone is unafraid to show how much they care.", traits: { softness: 32, energy: 96, mystery: 42, structure: 52 } },
            { id: "specific", title: "Quiet but very thoughtful", description: "Remembering a phrase, finding the right thing, noticing a detail.", traits: { softness: 90, energy: 22, mystery: 80, structure: 66 } },
            { id: "sudden", title: "Unexpected and spontaneous", description: "No occasion needed. Just because they wanted to.", traits: { softness: 54, energy: 90, mystery: 32, structure: 16 } },
            { id: "beautiful", title: "Thought through to the last detail", description: "A beautiful route, the right moment and a feeling of care.", traits: { softness: 58, energy: 38, mystery: 56, structure: 94 } }
        ]
    },
    {
        note: "The finishing touch",
        title: "If a bouquet could say one thing, what would it be?",
        options: [
            { id: "near", title: "“I am here”", description: "No grand words, just lasting, real presence.", traits: { softness: 96, energy: 22, mystery: 46, structure: 52 } },
            { id: "look", title: "“Look at me”", description: "Bold, bright and without hiding any feelings.", traits: { softness: 28, energy: 98, mystery: 76, structure: 44 } },
            { id: "escape", title: "“Let us escape somewhere”", description: "Lightness, movement and a little shared secret.", traits: { softness: 58, energy: 88, mystery: 38, structure: 16 } },
            { id: "choose", title: "“I chose you thoughtfully”", description: "A clear, beautiful choice, not a passing impulse.", traits: { softness: 66, energy: 34, mystery: 68, structure: 96 } }
        ]
    }
];
const views = ["landingView", "quizView", "resultView", "giftView"];
const answers = {};
const imageCache = new Map();
let currentQuestion = 0;
let currentResult = archetypes["wild-tenderness"];
let currentTraits = { softness: 70, energy: 52, mystery: 44, structure: 36 };
let currentGift = null;
let savedLink = null;
let previewTimer = null;
let toastTimer = null;
const elements = {
    headerStart: document.getElementById("headerStart"),
    heroStart: document.getElementById("heroStart"),
    progressText: document.getElementById("progressText"),
    petalProgress: document.getElementById("petalProgress"),
    questionFrame: document.getElementById("questionFrame"),
    questionNote: document.getElementById("questionNote"),
    questionTitle: document.getElementById("questionTitle"),
    answerGrid: document.getElementById("answerGrid"),
    backButton: document.getElementById("backButton"),
    nextButton: document.getElementById("nextButton"),
    quizPreviewImage: document.getElementById("quizPreviewImage"),
    quizPreviewTitle: document.getElementById("quizPreviewTitle"),
    quizPreviewCount: document.getElementById("quizPreviewCount"),
    resultView: document.getElementById("resultView"),
    resultImage: document.getElementById("resultImage"),
    resultImageDetail: document.getElementById("resultImageDetail"),
    resultImageBouquet: document.getElementById("resultImageBouquet"),
    resultKicker: document.getElementById("resultKicker"),
    resultTitle: document.getElementById("resultTitle"),
    resultPortrait: document.getElementById("resultPortrait"),
    resultSignals: document.getElementById("resultSignals"),
    formulaName: document.getElementById("formulaName"),
    formulaWhy: document.getElementById("formulaWhy"),
    flowerList: document.getElementById("flowerList"),
    palette: document.getElementById("palette"),
    floristNote: document.getElementById("floristNote"),
    storyPreview: document.getElementById("storyPreview"),
    shareStory: document.getElementById("shareStory"),
    downloadStory: document.getElementById("downloadStory"),
    copyHint: document.getElementById("copyHint"),
    shareStatus: document.getElementById("shareStatus"),
    restartButton: document.getElementById("restartButton"),
    giftTitle: document.getElementById("giftTitle"),
    giftHint: document.getElementById("giftHint"),
    giftImage: document.getElementById("giftImage"),
    giftBouquet: document.getElementById("giftBouquet"),
    giftDescription: document.getElementById("giftDescription"),
    copyGift: document.getElementById("copyGift"),
    toast: document.getElementById("toast")
};
function showView(id) {
    views.forEach((viewId) => {
        const node = document.getElementById(viewId);
        const isCurrent = viewId === id;
        node.hidden = !isCurrent;
        node.classList.toggle("is-active", isCurrent);
    });
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
}
function startFreshQuiz() {
    Object.keys(answers).forEach((key) => delete answers[key]);
    currentQuestion = 0;
    savedLink = null;
    showView("quizView");
    renderQuestion();
    updatePreview();
}
function renderProgress() {
    elements.progressText.textContent = `${String(currentQuestion + 1).padStart(2, "0")} / ${String(questions.length).padStart(2, "0")}`;
    elements.petalProgress.textContent = "";
    questions.forEach((question, index) => {
        const petal = document.createElement("span");
        if (index <= currentQuestion)
            petal.classList.add("is-done");
        petal.setAttribute("aria-hidden", "true");
        elements.petalProgress.appendChild(petal);
    });
    elements.petalProgress.setAttribute("aria-label", `Question ${currentQuestion + 1} of ${questions.length}`);
}
function buildAnswerCard(option, selected) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "answer-card";
    button.dataset.optionId = option.id;
    button.setAttribute("aria-pressed", selected ? "true" : "false");
    if (selected)
        button.classList.add("is-selected");
    if (option.art) {
        button.classList.add("has-art");
        const image = document.createElement("img");
        image.src = option.art;
        image.alt = "";
        image.loading = "lazy";
        button.appendChild(image);
    }
    const copy = document.createElement("div");
    if (option.art)
        copy.className = "answer-art-copy";
    const title = document.createElement("span");
    title.className = "answer-title";
    title.textContent = option.title;
    copy.appendChild(title);
    const description = document.createElement("span");
    description.className = "answer-description";
    description.textContent = option.description;
    copy.appendChild(description);
    if (option.swatches) {
        const swatches = document.createElement("div");
        swatches.className = "answer-swatches";
        swatches.setAttribute("aria-hidden", "true");
        option.swatches.forEach((color) => {
            const swatch = document.createElement("span");
            swatch.style.backgroundColor = color;
            swatches.appendChild(swatch);
        });
        copy.appendChild(swatches);
    }
    button.appendChild(copy);
    button.addEventListener("click", () => selectAnswer(option.id));
    return button;
}
function renderQuestion() {
    const question = questions[currentQuestion];
    const selectedId = answers[currentQuestion];
    renderProgress();
    elements.questionFrame.style.animation = "none";
    void elements.questionFrame.offsetHeight;
    elements.questionFrame.style.animation = "";
    elements.questionNote.textContent = question.note;
    elements.questionTitle.textContent = question.title;
    elements.answerGrid.textContent = "";
    question.options.forEach((option) => {
        elements.answerGrid.appendChild(buildAnswerCard(option, selectedId === option.id));
    });
    elements.backButton.style.visibility = currentQuestion === 0 ? "hidden" : "visible";
    elements.nextButton.disabled = !selectedId;
    elements.nextButton.textContent = currentQuestion === questions.length - 1 ? "Build my bouquet" : "Next";
}
function selectAnswer(optionId) {
    answers[currentQuestion] = optionId;
    const cards = elements.answerGrid.querySelectorAll(".answer-card");
    cards.forEach((card) => {
        const selected = card.dataset.optionId === optionId;
        card.classList.toggle("is-selected", selected);
        card.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    elements.nextButton.disabled = false;
    updatePreview();
}
function selectedOptions() {
    return questions.map((question, index) => {
        const selectedId = answers[index];
        return question.options.find((option) => option.id === selectedId);
    }).filter(Boolean);
}
function calculateTraits() {
    const options = selectedOptions();
    if (!options.length)
        return { softness: 70, energy: 52, mystery: 44, structure: 36 };
    const sums = { softness: 0, energy: 0, mystery: 0, structure: 0 };
    options.forEach((option) => {
        Object.keys(sums).forEach((key) => {
            sums[key] += option.traits[key];
        });
    });
    Object.keys(sums).forEach((key) => {
        sums[key] = Math.round(sums[key] / options.length);
    });
    return sums;
}
function closestArchetype(traits) {
    const centeredTraits = Object.keys(traits).map((key) => traits[key] - 50);
    const traitMagnitude = Math.sqrt(centeredTraits.reduce((sum, value) => sum + value * value, 0));
    return Object.values(archetypes).reduce((best, archetype) => {
        const centeredPrototype = Object.keys(traits).map((key) => archetype.prototype[key] - 50);
        const prototypeMagnitude = Math.sqrt(centeredPrototype.reduce((sum, value) => sum + value * value, 0));
        const dotProduct = centeredTraits.reduce((sum, value, index) => sum + value * centeredPrototype[index], 0);
        const score = traitMagnitude && prototypeMagnitude
            ? dotProduct / (traitMagnitude * prototypeMagnitude)
            : -1;
        return !best || score > best.score ? { archetype, score } : best;
    }, null).archetype;
}
function updatePreview() {
    const traits = calculateTraits();
    const result = closestArchetype(traits);
    const count = selectedOptions().length;
    clearTimeout(previewTimer);
    elements.quizPreviewImage.classList.add("is-changing");
    previewTimer = window.setTimeout(() => {
        elements.quizPreviewImage.src = result.image;
        elements.quizPreviewImage.alt = result.imageAlt;
        elements.quizPreviewImage.classList.remove("is-changing");
    }, 120);
    elements.quizPreviewTitle.textContent = result.preview;
    elements.quizPreviewCount.textContent = count
        ? `Already ${count} ${declension(count, ["answer", "answers", "answers"])} of ${questions.length}`
        : "Add your first answer";
}
function declension(number, forms) {
    const tens = number % 100;
    const units = number % 10;
    if (tens > 10 && tens < 20)
        return forms[2];
    if (units === 1)
        return forms[0];
    if (units > 1 && units < 5)
        return forms[1];
    return forms[2];
}
function goNext() {
    if (!answers[currentQuestion])
        return;
    if (currentQuestion < questions.length - 1) {
        currentQuestion += 1;
        renderQuestion();
        return;
    }
    renderResult();
}
function goBack() {
    if (currentQuestion === 0)
        return;
    currentQuestion -= 1;
    renderQuestion();
}
function renderSignals(result) {
    elements.resultSignals.textContent = "";
    result.signals.forEach((signal) => {
        const row = document.createElement("p");
        row.textContent = signal;
        elements.resultSignals.appendChild(row);
    });
}
function renderFlowerFormula(result) {
    elements.flowerList.textContent = "";
    result.flowers.forEach((flower) => {
        const item = document.createElement("div");
        item.className = "flower-item";
        const role = document.createElement("span");
        role.textContent = flower.role;
        const name = document.createElement("strong");
        name.textContent = flower.name;
        item.append(role, name);
        elements.flowerList.appendChild(item);
    });
    elements.palette.textContent = "";
    result.palette.forEach((color) => {
        const swatch = document.createElement("span");
        swatch.style.backgroundColor = color;
        swatch.title = color;
        elements.palette.appendChild(swatch);
    });
}
async function renderResult() {
    currentTraits = calculateTraits();
    currentResult = closestArchetype(currentTraits);
    savedLink = null;
    elements.resultImage.src = currentResult.image;
    elements.resultImage.alt = currentResult.imageAlt;
    elements.resultImageDetail.src = currentResult.gallery[1];
    elements.resultImageDetail.alt = `Look and mood: ${currentResult.name}`;
    elements.resultImageBouquet.src = currentResult.gallery[2];
    elements.resultImageBouquet.alt = `Recommended bouquet: ${currentResult.formula}`;
    elements.resultKicker.textContent = `Your bouquet · ${currentResult.name}`;
    elements.resultTitle.textContent = currentResult.name;
    elements.resultPortrait.textContent = currentResult.portrait;
    elements.formulaName.textContent = currentResult.formula;
    elements.formulaWhy.textContent = currentResult.why;
    elements.floristNote.textContent = currentResult.florist;
    elements.shareStatus.textContent = "";
    renderSignals(currentResult);
    renderFlowerFormula(currentResult);
    showView("resultView");
    try {
        await drawStoryCard(elements.storyPreview, currentResult);
    }
    catch (error) {
        elements.shareStatus.textContent = "The preview did not load. You can still try downloading.";
    }
}
function showToast(message) {
    clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("is-visible");
    toastTimer = window.setTimeout(() => elements.toast.classList.remove("is-visible"), 2800);
}
function loadImage(src) {
    if (imageCache.has(src))
        return imageCache.get(src);
    const promise = new Promise((resolve, reject) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(`Image did not load: ${src}`));
        image.src = src;
    });
    imageCache.set(src, promise);
    return promise;
}
function roundedPath(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
}
function drawCover(ctx, image, x, y, width, height) {
    const scale = Math.max(width / image.width, height / image.height);
    const sourceWidth = width / scale;
    const sourceHeight = height / scale;
    const sourceX = (image.width - sourceWidth) / 2;
    const sourceY = (image.height - sourceHeight) / 2;
    ctx.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, x, y, width, height);
}
function wrapText(ctx, text, maxWidth) {
    const words = String(text).split(/\s+/);
    const lines = [];
    let line = "";
    words.forEach((word) => {
        const test = line ? `${line} ${word}` : word;
        if (line && ctx.measureText(test).width > maxWidth) {
            lines.push(line);
            line = word;
        }
        else {
            line = test;
        }
    });
    if (line)
        lines.push(line);
    return lines;
}
function drawWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
    const lines = wrapText(ctx, text, maxWidth).slice(0, maxLines);
    lines.forEach((line, index) => ctx.fillText(line, x, y + index * lineHeight));
    return y + lines.length * lineHeight;
}
function drawRoundedCover(ctx, image, x, y, width, height, radius) {
    ctx.save();
    roundedPath(ctx, x, y, width, height, radius);
    ctx.clip();
    drawCover(ctx, image, x, y, width, height);
    ctx.restore();
}
async function drawStoryCard(canvas, result) {
    await document.fonts.ready;
    const images = await Promise.all(result.gallery.map((src) => loadImage(src)));
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = result.story.bg;
    ctx.fillRect(0, 0, width, height);
    ctx.save();
    ctx.globalAlpha = 0.13;
    ctx.fillStyle = result.story.accent;
    ctx.beginPath();
    ctx.arc(930, 180, 260, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(80, 1680, 340, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.fillStyle = result.story.accent;
    ctx.font = "700 26px Manrope, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("MY FLOWER VIBE", 72, 96);
    ctx.fillStyle = result.story.ink;
    ctx.font = "600 72px Unbounded, sans-serif";
    const titleBottom = drawWrappedText(ctx, result.name, 72, 178, 920, 84, 2);
    const imageY = Math.max(344, titleBottom + 48);
    const mainWidth = 610;
    const sideX = 706;
    drawRoundedCover(ctx, images[0], 72, imageY, mainWidth, 884, 42);
    drawRoundedCover(ctx, images[1], sideX, imageY, 302, 430, 34);
    drawRoundedCover(ctx, images[2], sideX, imageY + 454, 302, 430, 34);
    const bodyY = imageY + 884 + 66;
    ctx.fillStyle = result.story.accent;
    ctx.font = "700 22px Manrope, sans-serif";
    ctx.fillText("YOUR BOUQUET", 72, bodyY);
    ctx.fillStyle = result.story.ink;
    ctx.font = "600 42px Manrope, sans-serif";
    const formulaBottom = drawWrappedText(ctx, result.formula, 72, bodyY + 62, 920, 52, 2);
    ctx.font = "600 27px Manrope, sans-serif";
    ctx.fillStyle = result.story.ink;
    drawWrappedText(ctx, result.portrait, 72, formulaBottom + 34, 900, 38, 2);
    ctx.fillStyle = result.story.ink;
    ctx.font = "600 26px Manrope, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("Your subtle hint is ready", 1008, height - 114);
    ctx.fillStyle = result.story.accent;
    ctx.font = "700 23px Manrope, sans-serif";
    ctx.fillText("wai.computer/school/projects/bouquet/", 1008, height - 72);
    ctx.save();
    for (let index = 0; index < 1400; index += 1) {
        const alpha = Math.random() * 0.05;
        ctx.fillStyle = `rgba(25,22,30,${alpha})`;
        const size = Math.random() > 0.86 ? 2 : 1;
        ctx.fillRect(Math.random() * width, Math.random() * height, size, size);
    }
    ctx.restore();
}
function canvasBlob(canvas) {
    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Could not create the PNG")), "image/png");
    });
}
async function buildStoryBlob() {
    await drawStoryCard(elements.storyPreview, currentResult);
    return canvasBlob(elements.storyPreview);
}
function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1800);
}
async function downloadStory() {
    setBusy(elements.downloadStory, true, "Creating PNG");
    try {
        const blob = await buildStoryBlob();
        downloadBlob(blob, `fleur-${currentResult.key}.png`);
        showToast("Card saved");
    }
    catch (error) {
        showToast("Could not create the image");
    }
    finally {
        setBusy(elements.downloadStory, false, "Download PNG");
    }
}
async function shareStory() {
    setBusy(elements.shareStory, true, "Preparing your story");
    try {
        const blob = await buildStoryBlob();
        const file = new File([blob], `fleur-${currentResult.key}.png`, { type: "image/png" });
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
            await navigator.share({
                files: [file],
                title: `My flower vibe: ${currentResult.name}`,
                text: "This feels like a very good hint about my ideal bouquet."
            });
            elements.shareStatus.textContent = "Ready. If Instagram is installed, it will appear in the app menu.";
        }
        else {
            downloadBlob(blob, `fleur-${currentResult.key}.png`);
            elements.shareStatus.textContent = "This browser cannot share files directly, so the PNG has been downloaded.";
            showToast("PNG downloaded. Add it to your story");
        }
    }
    catch (error) {
        if (error && error.name === "AbortError")
            return;
        showToast("Could not open the share menu");
    }
    finally {
        setBusy(elements.shareStory, false, "Share to Stories");
    }
}
function setBusy(button, busy, label) {
    button.disabled = busy;
    button.textContent = label;
    button.setAttribute("aria-busy", busy ? "true" : "false");
}
function baseUrl() {
    return `${location.origin}${location.pathname}`;
}
function buildHintMessage(link) {
    return `${currentResult.hint}

My result: ${currentResult.name}\n${currentResult.formula}\n${link}`;
}
async function ensureSavedLink() {
    if (savedLink)
        return savedLink;
    const payload = {
        resultKey: currentResult.key,
        bouquet: currentResult.formula,
        hint: currentResult.hint,
        description: currentResult.why,
        photo: new URL(currentResult.image, location.href).href,
        palette: currentResult.palette
    };
    const response = await fetch(`${DB}/saved`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nick: "no name", payload })
    });
    if (!response.ok)
        throw new Error("Could not save the hint");
    const data = await response.json();
    if (!data.id)
        throw new Error("The database did not return a link");
    savedLink = `${baseUrl()}?id=${encodeURIComponent(data.id)}`;
    return savedLink;
}
async function copyHint() {
    setBusy(elements.copyHint, true, "Saving the link");
    try {
        const link = await ensureSavedLink();
        await navigator.clipboard.writeText(buildHintMessage(link));
        showToast("Hint and link copied");
        elements.shareStatus.textContent = "Paste the text into a private message. The link opens your exact bouquet.";
    }
    catch (error) {
        showToast("Could not copy. Check your connection and try again");
    }
    finally {
        setBusy(elements.copyHint, false, "Copy the hint");
    }
}
function safeImageUrl(value, fallback) {
    try {
        const url = new URL(value, location.href);
        const allowedHost = url.host === location.host || url.host === "images.unsplash.com";
        return url.protocol === "https:" && allowedHost ? url.href : fallback;
    }
    catch (error) {
        return fallback;
    }
}
function legacyGift(payload) {
    const bouquet = payload.bouquet || "Surprise bouquet";
    const details = [payload.description, payload.price].filter(Boolean).join(" ");
    return {
        formula: bouquet,
        hint: payload.hint || "Someone left you a floral hint.",
        why: details || "Take a look at the arrangement and save the idea for the right moment.",
        image: safeImageUrl(payload.photo, archetypes["wild-tenderness"].image),
        imageAlt: `Bouquet ${bouquet}`
    };
}
async function loadGift(id) {
    showView("giftView");
    elements.giftTitle.textContent = "Looking for a bouquet idea? Here it is.";
    elements.giftHint.textContent = "Loading the hint…";
    elements.copyGift.disabled = true;
    try {
        const response = await fetch(`${DB}/saved?limit=500&order=desc`);
        if (!response.ok)
            throw new Error("Could not load the hint");
        const data = await response.json();
        const record = (data.items || []).find((item) => String(item.id) === String(id));
        if (!record)
            throw new Error("Hint not found");
        const payload = record.payload || {};
        const result = archetypes[payload.resultKey] || legacyGift(payload);
        currentGift = result;
        elements.giftHint.textContent = payload.hint || result.hint;
        elements.giftImage.src = safeImageUrl(payload.photo || result.image, result.image);
        elements.giftImage.alt = result.imageAlt;
        elements.giftBouquet.textContent = payload.bouquet || result.formula;
        elements.giftDescription.textContent = payload.description || result.why;
        elements.copyGift.disabled = false;
    }
    catch (error) {
        currentGift = null;
        elements.giftTitle.textContent = "This hint has gone missing.";
        elements.giftHint.textContent = "Take the quiz again to create a new link.";
        elements.giftBouquet.textContent = "A new bouquet awaits";
        elements.giftDescription.textContent = "Seven choices help find the right arrangement.";
        elements.giftImage.src = archetypes["wild-tenderness"].image;
        elements.copyGift.disabled = true;
    }
}
async function copyGiftFormula() {
    if (!currentGift)
        return;
    const formula = currentGift.formula || "Bouquet";
    const florist = currentGift.florist ? `\n${currentGift.florist}` : "";
    try {
        await navigator.clipboard.writeText(`${formula}${florist}`);
        showToast("Flower list copied");
    }
    catch (error) {
        showToast("Could not copy the flower list");
    }
}
elements.heroStart.addEventListener("click", startFreshQuiz);
elements.headerStart.addEventListener("click", startFreshQuiz);
elements.nextButton.addEventListener("click", goNext);
elements.backButton.addEventListener("click", goBack);
elements.restartButton.addEventListener("click", startFreshQuiz);
elements.downloadStory.addEventListener("click", downloadStory);
elements.shareStory.addEventListener("click", shareStory);
elements.copyHint.addEventListener("click", copyHint);
elements.copyGift.addEventListener("click", copyGiftFormula);
const query = new URLSearchParams(location.search);
const giftId = query.get("id") || query.get("b");
if (giftId) {
    loadGift(giftId);
}
else {
    showView("landingView");
}
