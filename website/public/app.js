// Configuration
const API_URL = 'http://localhost:8000';
const TILE_SIZE = 256;

// State
let currentProduct = null;
let zoom = 1;
let pan = { x: 0, y: 0 };
let isDragging = false;
let dragStart = { x: 0, y: 0 };
let tileImages = new Map();
let loadingTiles = new Set();

// DOM Elements
const canvas = document.getElementById('mapCanvas');
const ctx = canvas.getContext('2d');
const productSelect = document.getElementById('productSelect');
const zoomInBtn = document.getElementById('zoomIn');
const zoomOutBtn = document.getElementById('zoomOut');
const resetBtn = document.getElementById('resetView');
const cacheForm = document.getElementById('cacheForm');
const quickCacheBtn = document.getElementById('quickCacheBtn');

// Initialize
function init() {
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    
    // Load products
    loadProducts();
    
    // Event listeners
    canvas.addEventListener('mousedown', handleMouseDown);
    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseup', handleMouseUp);
    canvas.addEventListener('mouseleave', handleMouseUp);
    
    // Mouse wheel zoom
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    
    zoomInBtn.addEventListener('click', () => setZoom(zoom + 1));
    zoomOutBtn.addEventListener('click', () => setZoom(zoom - 1));
    resetBtn.addEventListener('click', resetView);
    productSelect.addEventListener('change', handleProductChange);
    cacheForm.addEventListener('submit', handleCacheTiles);
    quickCacheBtn.addEventListener('click', handleQuickCache);
    
    // Touch support
    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove', handleTouchMove, { passive: false });
    canvas.addEventListener('touchend', handleTouchEnd);
    
    // Start render loop
    render();
}

function resizeCanvas() {
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    if (currentProduct) {
        loadVisibleTiles();
    }
}

async function loadProducts() {
    try {
        const response = await fetch(`${API_URL}/products`);
        const data = await response.json();
        
        productSelect.innerHTML = '';
        
        if (data.products.length === 0) {
            productSelect.innerHTML = '<option>No products available</option>';
            return;
        }
        
        data.products.forEach(product => {
            const option = document.createElement('option');
            option.value = product.id;
            option.textContent = `${product.name} (cached: ${product.cached_tiles} tiles)`;
            option.dataset.info = JSON.stringify(product);
            productSelect.appendChild(option);
        });
        
        // Load first product
        if (data.products.length > 0) {
            currentProduct = data.products[0];
            updateProductInfo(currentProduct);
            resetView();
        }
    } catch (error) {
        console.error('Error loading products:', error);
        productSelect.innerHTML = '<option>Error loading products</option>';
    }
}

function handleProductChange(e) {
    const option = e.target.selectedOptions[0];
    if (option && option.dataset.info) {
        currentProduct = JSON.parse(option.dataset.info);
        updateProductInfo(currentProduct);
        resetView();
        clearTileCache();
        loadVisibleTiles();
    }
}

function updateProductInfo(product) {
    const infoDiv = document.getElementById('productInfo');
    infoDiv.innerHTML = `
        <p class="product-name">${product.name}</p>
        <p class="product-desc">${product.description}</p>
        <p class="product-desc" style="margin-top: 8px;">Max Zoom: ${product.max_zoom} | Cached: ${product.cached_tiles} tiles</p>
    `;
    
    // Update zoom limits
    document.getElementById('cacheZoom').max = product.max_zoom;
}

function resetView() {
    zoom = 1;
    pan = { x: canvas.width / 2 - (TILE_SIZE / 2), y: canvas.height / 2 - (TILE_SIZE / 2) };
    updateInfo();
}

function setZoom(newZoom) {
    if (!currentProduct) return;
    
    const oldZoom = zoom;
    zoom = Math.max(0, Math.min(currentProduct.max_zoom, newZoom));
    
    if (zoom !== oldZoom) {
        // Zoom towards center
        const centerX = canvas.width / 2;
        const centerY = canvas.height / 2;
        const scale = Math.pow(2, zoom - oldZoom);
        
        pan.x = centerX - (centerX - pan.x) * scale;
        pan.y = centerY - (centerY - pan.y) * scale;
        
        clearTileCache();
        loadVisibleTiles();
        updateInfo();
    }
}

function clearTileCache() {
    tileImages.clear();
    loadingTiles.clear();
}

// Mouse events
function handleMouseDown(e) {
    isDragging = true;
    dragStart = {
        x: e.clientX - pan.x,
        y: e.clientY - pan.y
    };
    canvas.style.cursor = 'grabbing';
}

function handleMouseMove(e) {
    if (!isDragging) return;
    
    pan = {
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y
    };
    
    loadVisibleTiles();
    updateInfo();
}

function handleMouseUp() {
    isDragging = false;
    canvas.style.cursor = 'grab';
}

function handleWheel(e) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -1 : 1;
    setZoom(zoom + delta);
}

// Touch events
function handleTouchStart(e) {
    e.preventDefault();
    const touch = e.touches[0];
    handleMouseDown({ clientX: touch.clientX, clientY: touch.clientY });
}

function handleTouchMove(e) {
    e.preventDefault();
    const touch = e.touches[0];
    handleMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
}

function handleTouchEnd(e) {
    e.preventDefault();
    handleMouseUp();
}

// Calculate visible tiles
function getVisibleTiles() {
    if (!currentProduct) return [];
    
    const tileScale = TILE_SIZE * Math.pow(2, zoom);
    const tilesInView = Math.pow(2, zoom);
    
    const startCol = Math.max(0, Math.floor(-pan.x / tileScale));
    const endCol = Math.min(tilesInView - 1, Math.ceil((canvas.width - pan.x) / tileScale));
    const startRow = Math.max(0, Math.floor(-pan.y / tileScale));
    const endRow = Math.min(tilesInView - 1, Math.ceil((canvas.height - pan.y) / tileScale));
    
    const tiles = [];
    for (let row = startRow; row <= endRow; row++) {
        for (let col = startCol; col <= endCol; col++) {
            tiles.push({ row, col, zoom });
        }
    }
    return tiles;
}

// Load tiles from API
async function loadVisibleTiles() {
    if (!currentProduct) return;
    
    const visibleTiles = getVisibleTiles();
    
    for (const tile of visibleTiles) {
        const key = `${tile.zoom}-${tile.row}-${tile.col}`;
        
        if (!tileImages.has(key) && !loadingTiles.has(key)) {
            loadingTiles.add(key);
            updateCacheStatus('loading');
            
            try {
                const url = `${API_URL}/tile/${currentProduct.id}/${tile.zoom}/${tile.row}/${tile.col}`;
                const response = await fetch(url);
                
                if (response.ok) {
                    const blob = await response.blob();
                    const img = new Image();
                    img.src = URL.createObjectURL(blob);
                    
                    await new Promise((resolve, reject) => {
                        img.onload = resolve;
                        img.onerror = reject;
                    });
                    
                    tileImages.set(key, img);
                    console.log(`Loaded tile: ${currentProduct.id} z${tile.zoom} [${tile.row},${tile.col}]`);
                } else {
                    console.error(`Failed to load tile: ${key}`);
                }
            } catch (error) {
                console.error(`Error loading tile ${key}:`, error);
            } finally {
                loadingTiles.delete(key);
                updateCacheStatus('ready');
            }
        }
    }
    
    updateInfo();
}

// Render loop
function render() {
    // Clear canvas with space background
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
    gradient.addColorStop(0, '#000000');
    gradient.addColorStop(1, '#0a0a0a');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    if (currentProduct) {
        const visibleTiles = getVisibleTiles();
        const tileScale = TILE_SIZE * Math.pow(2, zoom);
        
        // Draw tiles
        visibleTiles.forEach(({ row, col, zoom: z }) => {
            const x = col * tileScale + pan.x;
            const y = row * tileScale + pan.y;
            
            const key = `${z}-${row}-${col}`;
            const img = tileImages.get(key);
            
            if (img) {
                ctx.drawImage(img, x, y, tileScale, tileScale);
            } else {
                // Draw placeholder
                ctx.fillStyle = '#1a1a1a';
                ctx.fillRect(x, y, tileScale, tileScale);
                
                // Draw grid
                ctx.strokeStyle = 'rgba(100, 181, 246, 0.2)';
                ctx.lineWidth = 1;
                ctx.strokeRect(x, y, tileScale, tileScale);
                
                // Draw loading text
                if (loadingTiles.has(key)) {
                    ctx.fillStyle = 'rgba(100, 181, 246, 0.6)';
                    ctx.font = '12px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText('Downloading...', x + tileScale / 2, y + tileScale / 2 - 5);
                    ctx.fillText(`z${z} [${row},${col}]`, x + tileScale / 2, y + tileScale / 2 + 10);
                } else {
                    ctx.fillStyle = 'rgba(168, 178, 209, 0.4)';
                    ctx.font = '11px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(`Tile z${z}`, x + tileScale / 2, y + tileScale / 2 - 5);
                    ctx.fillText(`[${row},${col}]`, x + tileScale / 2, y + tileScale / 2 + 10);
                }
            }
            
            // Draw subtle border
            ctx.strokeStyle = 'rgba(100, 181, 246, 0.15)';
            ctx.lineWidth = 1;
            ctx.strokeRect(x, y, tileScale, tileScale);
        });
    } else {
        // Draw welcome message
        ctx.fillStyle = 'rgba(100, 181, 246, 0.8)';
        ctx.font = '24px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('🌙 NASA LROC Moon Viewer', canvas.width / 2, canvas.height / 2 - 20);
        ctx.font = '14px sans-serif';
        ctx.fillStyle = 'rgba(168, 178, 209, 0.8)';
        ctx.fillText('Select a product to view lunar imagery', canvas.width / 2, canvas.height / 2 + 10);
    }
    
    requestAnimationFrame(render);
}

function updateInfo() {
    document.getElementById('zoomLevel').textContent = zoom;
    document.getElementById('zoomDisplay').textContent = `Zoom: ${zoom}`;
    document.getElementById('panInfo').textContent = `(${Math.round(pan.x)}, ${Math.round(pan.y)})`;
    document.getElementById('tileCount').textContent = tileImages.size;
}

function updateCacheStatus(status) {
    const statusEl = document.getElementById('cacheStatus');
    if (status === 'loading') {
        statusEl.textContent = 'Downloading...';
        statusEl.style.color = '#64b5f6';
    } else {
        statusEl.textContent = 'Ready';
        statusEl.style.color = '#4caf50';
    }
}

// Cache tiles form
async function handleCacheTiles(e) {
    e.preventDefault();
    
    if (!currentProduct) {
        alert('Please select a product first');
        return;
    }
    
    const zoom = document.getElementById('cacheZoom').value;
    const startRow = document.getElementById('startRow').value;
    const endRow = document.getElementById('endRow').value;
    const startCol = document.getElementById('startCol').value;
    const endCol = document.getElementById('endCol').value;
    
    const statusDiv = document.getElementById('cacheStatus2');
    const tileCount = (parseInt(endRow) - parseInt(startRow) + 1) * 
                     (parseInt(endCol) - parseInt(startCol) + 1);
    
    statusDiv.textContent = `🔽 Caching ${tileCount} tiles in background... This may take a few minutes.`;
    statusDiv.className = 'info';
    
    try {
        const url = `${API_URL}/generate/${currentProduct.id}?zoom=${zoom}&start_row=${startRow}&end_row=${endRow}&start_col=${startCol}&end_col=${endCol}`;
        const response = await fetch(url, { method: 'POST' });
        
        const data = await response.json();
        
        if (response.ok) {
            statusDiv.textContent = `✓ ${data.message}. Tiles are being downloaded from NASA LROC.`;
            statusDiv.className = 'success';
            
            // Reload product info after a delay
            setTimeout(() => {
                loadProducts();
            }, 3000);
        } else {
            statusDiv.textContent = `✗ Error: ${data.detail}`;
            statusDiv.className = 'error';
        }
    } catch (error) {
        statusDiv.textContent = `✗ Error: ${error.message}`;
        statusDiv.className = 'error';
    }
}

// Quick cache function for floating button
async function handleQuickCache() {
    if (!currentProduct) {
        alert('Please select a product first');
        return;
    }
    
    const visibleTiles = getVisibleTiles();
    if (visibleTiles.length === 0) {
        alert('No tiles to cache');
        return;
    }
    
    // Calculate tile range from visible tiles
    const rows = visibleTiles.map(t => t.row);
    const cols = visibleTiles.map(t => t.col);
    const zoom = visibleTiles[0].zoom;
    
    const startRow = Math.min(...rows);
    const endRow = Math.max(...rows);
    const startCol = Math.min(...cols);
    const endCol = Math.max(...cols);
    
    const tileCount = (endRow - startRow + 1) * (endCol - startCol + 1);
    
    // Update button text
    const originalText = quickCacheBtn.textContent;
    quickCacheBtn.textContent = '⏳ Caching...';
    quickCacheBtn.disabled = true;
    
    try {
        const url = `${API_URL}/generate/${currentProduct.id}?zoom=${zoom}&start_row=${startRow}&end_row=${endRow}&start_col=${startCol}&end_col=${endCol}`;
        const response = await fetch(url, { method: 'POST' });
        
        const data = await response.json();
        
        if (response.ok) {
            quickCacheBtn.textContent = '✅ Cached!';
            setTimeout(() => {
                quickCacheBtn.textContent = originalText;
                quickCacheBtn.disabled = false;
            }, 2000);
            
            // Reload product info after a delay
            setTimeout(() => {
                loadProducts();
            }, 3000);
        } else {
            quickCacheBtn.textContent = '❌ Error';
            setTimeout(() => {
                quickCacheBtn.textContent = originalText;
                quickCacheBtn.disabled = false;
            }, 2000);
        }
    } catch (error) {
        quickCacheBtn.textContent = '❌ Error';
        setTimeout(() => {
            quickCacheBtn.textContent = originalText;
            quickCacheBtn.disabled = false;
        }, 2000);
    }
}

// Start the app
init();

console.log('🌙 NASA LROC Moon Map Viewer initialized');
console.log('📡 API:', API_URL);
console.log('🗺️  Lunar imagery from NASA/GSFC/Arizona State University');