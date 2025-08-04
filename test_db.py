#!/usr/bin/env python3
"""
Test script to verify database functionality
"""

from database_setup import init_database, add_style, get_all_styles, get_styles_by_merchant, STAGE_LABELS

def test_database():
    """Test the database functionality."""
    print("Testing database functionality...")
    
    # Initialize database
    init_database()
    print("✓ Database initialized")
    
    # Add a test style
    style_id = add_style(
        merchant="Test Merchant",
        brand="Test Brand",
        style_no="TEST001",
        garment="Shirt",
        colour="Blue"
    )
    print(f"✓ Added test style with ID: {style_id}")
    
    # Get all styles
    all_styles = get_all_styles()
    print(f"✓ Found {len(all_styles)} styles in database")
    
    # Get styles by merchant
    merchant_styles = get_styles_by_merchant("Test Merchant")
    print(f"✓ Found {len(merchant_styles)} styles for Test Merchant")
    
    # Display the test style
    if merchant_styles:
        style = merchant_styles[0]
        print(f"✓ Test style details:")
        print(f"  - ID: {style.id}")
        print(f"  - Merchant: {style.merchant}")
        print(f"  - Brand: {style.brand}")
        print(f"  - Style No: {style.style_no}")
        print(f"  - Garment: {style.garment}")
        print(f"  - Colour: {style.colour}")
        print(f"  - Stage: {STAGE_LABELS[style.stage]}")
        print(f"  - Active: {style.active}")
        print(f"  - Created: {style.created_at}")
    
    print("\n🎉 Database test completed successfully!")

if __name__ == "__main__":
    test_database() 