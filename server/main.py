from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io
import os
from pathlib import Path
from functools import lru_cache
import requests
import uvicorn
from typing import Optional
import json

app = FastAPI(title="NASA LROC WMTS Tile Server", version="3.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
TILE_SIZE = 256
TILES_DIR = Path("tiles")
CACHE_SIZE = 200

# NASA Trek WMTS tile server base URL
WMTS_BASE = "https://trek.nasa.gov/tiles/Moon/EQ"

# NASA Trek WMTS Products - using NASA's official tile service
LROC_PRODUCTS = {
    "wac_global": {
        "name": "WAC Global Mosaic 100m",
        "description": "LRO Wide Angle Camera global mosaic at 100m/pixel",
        "layer": "LRO_WAC_Mosaic_Global_303ppd",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_WAC_Mosaic_Global_303ppd/1.0.0/default/default028mm",
        "max_zoom": 7,
        "tile_format": "jpg"
    },
    "wac_nearside": {
        "name": "WAC Nearside Mosaic",
        "description": "WAC Nearside mosaic",
        "layer": "LRO_WAC_Mosaic_Global_303ppd",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_WAC_Mosaic_Global_303ppd/1.0.0/default/default028mm",
        "max_zoom": 7,
        "tile_format": "jpg"
    },
    "wac_farside": {
        "name": "WAC Farside Mosaic",
        "description": "WAC Farside mosaic",
        "layer": "LRO_WAC_Mosaic_Global_303ppd",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_WAC_Mosaic_Global_303ppd/1.0.0/default/default028mm",
        "max_zoom": 7,
        "tile_format": "jpg"
    },
    "wac_color": {
        "name": "WAC Color Mosaic",
        "description": "LROC WAC Color Mosaic",
        "layer": "LRO_WAC_Color_Mosaic_Global_303ppd",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_WAC_Color_Mosaic_Global_303ppd/1.0.0/default/default028mm",
        "max_zoom": 5,
        "tile_format": "jpg"
    },
    "lola_color": {
        "name": "LOLA Color Shaded Relief",
        "description": "LOLA elevation with color coding",
        "layer": "LRO_LOLA_ClrShade_Global_128ppd_v06",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_LOLA_ClrShade_Global_128ppd_v06/1.0.0/default/default028mm",
        "max_zoom": 6,
        "tile_format": "png"
    },
    "lola_shade": {
        "name": "LOLA Shaded Relief",
        "description": "LOLA elevation shaded relief",
        "layer": "LRO_LOLA_Shade_Global_128ppd_v04",
        "wmts_endpoint": f"{WMTS_BASE}/LRO_LOLA_Shade_Global_128ppd_v04/1.0.0/default/default028mm",
        "max_zoom": 6,
        "tile_format": "png"
    },
    "kaguya_morning": {
        "name": "Kaguya Morning",
        "description": "Kaguya Terrain Camera morning mosaic",
        "layer": "Kaguya_TCMorningMap_Global_256ppd",
        "wmts_endpoint": f"{WMTS_BASE}/Kaguya_TCMorningMap_Global_256ppd/1.0.0/default/default028mm",
        "max_zoom": 6,
        "tile_format": "jpg"
    },
    "kaguya_evening": {
        "name": "Kaguya Evening",
        "description": "Kaguya Terrain Camera evening mosaic",
        "layer": "Kaguya_TCEveningMap_Global_256ppd",
        "wmts_endpoint": f"{WMTS_BASE}/Kaguya_TCEveningMap_Global_256ppd/1.0.0/default/default028mm",
        "max_zoom": 6,
        "tile_format": "jpg"
    }
}

# Ensure directories exist
TILES_DIR.mkdir(exist_ok=True)
for product in LROC_PRODUCTS.keys():
    (TILES_DIR / product).mkdir(exist_ok=True)

# Tile cache
tile_cache_file = Path("tile_cache.json")
if tile_cache_file.exists():
    with open(tile_cache_file, 'r') as f:
        MAPS_CONFIG = json.load(f)
else:
    MAPS_CONFIG = {}


def save_cache():
    """Save maps configuration to file"""
    with open(tile_cache_file, 'w') as f:
        json.dump(MAPS_CONFIG, f, indent=2)


@lru_cache(maxsize=CACHE_SIZE)
def get_cached_tile(map_id: str, zoom: int, row: int, col: int) -> bytes:
    """Get tile from cache or disk"""
    tile_format = LROC_PRODUCTS[map_id]["tile_format"]
    tile_path = TILES_DIR / map_id / f"tile_{zoom}_{row}_{col}.{tile_format}"
    
    if not tile_path.exists():
        # Return blank tile
        blank = Image.new('RGB', (TILE_SIZE, TILE_SIZE), color=(20, 20, 25))
        img_io = io.BytesIO()
        
        from PIL import ImageDraw
        draw = ImageDraw.Draw(blank)
        text = f"LROC QuickMap\nZoom: {zoom}\nTile: {row},{col}\nNot cached yet"
        draw.text((30, 80), text, fill=(120, 120, 130))
        
        blank.save(img_io, 'JPEG', quality=85)
        return img_io.getvalue()
    
    with open(tile_path, 'rb') as f:
        return f.read()


def download_quickmap_tile(product: str, zoom: int, row: int, col: int) -> Optional[Image.Image]:
    """
    Download tile from NASA Trek WMTS tile service
    Uses WMTS endpoint format: /{layer}/1.0.0/default/default028mm/{zoom}/{row}/{col}.{format}
    """
    try:
        product_info = LROC_PRODUCTS[product]
        tile_format = product_info['tile_format']
        wmts_endpoint = product_info['wmts_endpoint']

        # NASA Trek WMTS tile URL format: {wmts_endpoint}/{zoom}/{row}/{col}.{format}
        tile_url = f"{wmts_endpoint}/{zoom}/{row}/{col}.{tile_format}"

        print(f"Downloading from NASA Trek: {product} z{zoom} [{row},{col}]")
        print(f"URL: {tile_url}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://trek.nasa.gov/'
        }

        response = requests.get(tile_url, headers=headers, timeout=30)
        response.raise_for_status()

        # Verify we got an image
        content_type = response.headers.get('content-type', '')
        if 'image' not in content_type.lower():
            print(f"Warning: Unexpected content type: {content_type}")
            return None

        img = Image.open(io.BytesIO(response.content))
        print(f"✓ Successfully downloaded tile: {img.size} {img.mode}")
        return img

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Tile not available (404): {product} z{zoom} [{row},{col}]")
        else:
            print(f"HTTP Error {e.response.status_code}: {e}")
        return None
    except Exception as e:
        print(f"Error downloading tile: {e}")
        return None


@app.get("/")
async def root():
    """API Info"""
    return {
        "message": "NASA LROC WMTS Tile Server",
        "version": "3.0.0",
        "description": "Serving official LROC lunar imagery via WMTS endpoints",
        "endpoints": {
            "products": "/products - List available LROC products",
            "tile": "/tile/{product}/{zoom}/{row}/{col} - Get a tile",
            "generate": "/generate/{product}?zoom=Z&start_row=R&end_row=R&start_col=C&end_col=C - Cache tiles",
            "info": "/info/{product} - Product details",
            "clear": "/cache/{product} - Clear cache"
        },
        "data_source": "LROC WMTS (https://quickmap.lroc.asu.edu)",
        "note": "Official NASA Lunar Reconnaissance Orbiter Camera data via WMTS protocol"
    }


@app.get("/products")
async def list_products():
    """List available LROC WMTS products"""
    products = []
    for pid, info in LROC_PRODUCTS.items():
        tile_format = info["tile_format"]
        cached_tiles = len(list((TILES_DIR / pid).glob(f"*.{tile_format}")))
        products.append({
            "id": pid,
            "name": info["name"],
            "description": info["description"],
            "max_zoom": info["max_zoom"],
            "cached_tiles": cached_tiles,
            "format": tile_format,
            "layer": info["layer"]
        })
    return {
        "products": products,
        "source": "LROC WMTS"
    }


@app.get("/tile/{product}/{zoom}/{row}/{col}")
async def get_tile(product: str, zoom: int, row: int, col: int):
    """
    Get a tile - either from cache or download from LROC WMTS
    Uses WMTS tile scheme
    """
    if product not in LROC_PRODUCTS:
        raise HTTPException(status_code=404, detail=f"Product '{product}' not found")
    
    if zoom < 0 or zoom > LROC_PRODUCTS[product]["max_zoom"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid zoom level. Valid range: 0-{LROC_PRODUCTS[product]['max_zoom']}"
        )
    
    tile_format = LROC_PRODUCTS[product]["tile_format"]
    tile_path = TILES_DIR / product / f"tile_{zoom}_{row}_{col}.{tile_format}"
    
    if tile_path.exists():
        # Serve from cache
        print(f"Serving from cache: {product} z{zoom} [{row},{col}]")
        tile_data = get_cached_tile(product, zoom, row, col)
        media_type = f"image/{tile_format}"
    else:
        # Download from LROC WMTS
        img = download_quickmap_tile(product, zoom, row, col)
        
        if img:
            # Save to cache
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            if tile_format == 'png':
                img.save(tile_path, 'PNG', optimize=True)
            else:
                img.save(tile_path, 'JPEG', quality=90, optimize=True)
            
            # Convert to bytes
            img_io = io.BytesIO()
            if tile_format == 'png':
                img.save(img_io, 'PNG', optimize=True)
            else:
                img.save(img_io, 'JPEG', quality=90, optimize=True)
            tile_data = img_io.getvalue()
            media_type = f"image/{tile_format}"
        else:
            # Return blank tile on error
            print(f"Returning blank tile for: {product} z{zoom} [{row},{col}]")
            tile_data = get_cached_tile(product, zoom, row, col)
            media_type = "image/jpeg"
    
    return StreamingResponse(io.BytesIO(tile_data), media_type=media_type)


@app.post("/generate/{product}")
async def generate_tiles(
    product: str,
    background_tasks: BackgroundTasks,
    zoom: int = Query(2, ge=0, le=8),
    start_row: int = Query(0, ge=0),
    end_row: int = Query(4, ge=0),
    start_col: int = Query(0, ge=0),
    end_col: int = Query(4, ge=0)
):
    """
    Pre-cache tiles from LROC QuickMap for a specific region
    Downloads tiles in the background
    """
    if product not in LROC_PRODUCTS:
        raise HTTPException(status_code=404, detail=f"Product '{product}' not found")
    
    if zoom > LROC_PRODUCTS[product]["max_zoom"]:
        raise HTTPException(
            status_code=400, 
            detail=f"Max zoom for {product} is {LROC_PRODUCTS[product]['max_zoom']}"
        )
    
    tile_count = (end_row - start_row + 1) * (end_col - start_col + 1)
    tile_format = LROC_PRODUCTS[product]["tile_format"]
    
    def download_tiles():
        """Background task to download tiles"""
        downloaded = 0
        failed = 0
        skipped = 0
        
        print(f"\nStarting tile cache generation for {product}")
        print(f"Region: zoom={zoom}, rows={start_row}-{end_row}, cols={start_col}-{end_col}")
        print(f"Total tiles to process: {tile_count}\n")
        
        for row in range(start_row, end_row + 1):
            for col in range(start_col, end_col + 1):
                tile_path = TILES_DIR / product / f"tile_{zoom}_{row}_{col}.{tile_format}"
                
                if tile_path.exists():
                    skipped += 1
                    continue
                
                img = download_quickmap_tile(product, zoom, row, col)
                if img:
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    if tile_format == 'png':
                        img.save(tile_path, 'PNG', optimize=True)
                    else:
                        img.save(tile_path, 'JPEG', quality=90, optimize=True)
                    downloaded += 1
                    print(f"Cached tile [{row},{col}] ({downloaded + skipped}/{tile_count})")
                else:
                    failed += 1
                    print(f"Failed tile [{row},{col}]")
                    
        
        print(f"\nCache generation complete!")
        print(f"Downloaded: {downloaded} tiles")
        print(f"Skipped: {skipped} tiles (already cached)")
        print(f"Failed: {failed} tiles\n")
    
    background_tasks.add_task(download_tiles)
    
    return {
        "message": f"Caching {tile_count} tiles in background",
        "product": product,
        "product_name": LROC_PRODUCTS[product]["name"],
        "zoom": zoom,
        "region": {
            "rows": f"{start_row}-{end_row}",
            "cols": f"{start_col}-{end_col}"
        },
        "status": "Processing in background - check server logs for progress"
    }


@app.delete("/cache/{product}")
async def clear_cache(product: str):
    """Clear cached tiles for a product"""
    if product not in LROC_PRODUCTS:
        raise HTTPException(status_code=404, detail=f"Product '{product}' not found")
    
    tiles_dir = TILES_DIR / product
    deleted_count = 0
    
    if tiles_dir.exists():
        tile_format = LROC_PRODUCTS[product]["tile_format"]
        deleted_count = len(list(tiles_dir.glob(f"*.{tile_format}")))
        import shutil
        shutil.rmtree(tiles_dir)
        tiles_dir.mkdir()
    
    get_cached_tile.cache_clear()
    
    return {
        "message": f"Cache cleared for {product}",
        "product_name": LROC_PRODUCTS[product]["name"],
        "tiles_deleted": deleted_count
    }


@app.get("/info/{product}")
async def product_info(product: str):
    """Get detailed info about a LROC WMTS product"""
    if product not in LROC_PRODUCTS:
        raise HTTPException(status_code=404, detail=f"Product '{product}' not found")
    
    info = LROC_PRODUCTS[product].copy()
    tile_format = info["tile_format"]
    cached_files = list((TILES_DIR / product).glob(f"*.{tile_format}"))
    cached_tiles = len(cached_files)
    
    cache_size = sum(f.stat().st_size for f in cached_files) / (1024 * 1024) if cached_tiles > 0 else 0
    
    info["cached_tiles"] = cached_tiles
    info["cache_size_mb"] = round(cache_size, 2)
    info["tile_size"] = TILE_SIZE
    info["source"] = "LROC WMTS"
    
    return info


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "LROC WMTS Tile Server",
        "version": "3.0.0",
        "data_source": "https://quickmap.lroc.asu.edu"
    }


if __name__ == "__main__":
    print("\n" + "="*70)
    print("NASA LROC WMTS Tile Server")
    print("="*70)
    print("\nData Source: LROC WMTS (Official LROC tile service)")
    print("Website: https://quickmap.lroc.asu.edu")
    print("Instrument: Lunar Reconnaissance Orbiter Camera\n")
    print("Available Products:")
    for pid, info in LROC_PRODUCTS.items():
        print(f"  - {info['name']}")
        print(f"    {info['description']} (max zoom: {info['max_zoom']})")
    print("\n" + "="*70)
    print("Starting server...")
    print("API Endpoint: http://localhost:8000")
    print("Documentation: http://localhost:8000/docs")
    print("Products List: http://localhost:8000/products")
    print("Health Check: http://localhost:8000/health")
    print("="*70 + "\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")