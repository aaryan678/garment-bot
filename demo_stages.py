#!/usr/bin/env python3
"""
Demo script to show stage management functionality
"""

from database_setup import init_database, add_style, get_styles_by_merchant, update_style_stage, STAGE_LABELS

def demo_stage_management():
    """Demonstrate the stage management functionality."""
    print("🎭 Stage Management Demo")
    print("=" * 50)
    
    # Initialize database
    init_database()
    print("✓ Database initialized")
    
    # Add a test style
    style_id = add_style(
        merchant="Demo Merchant",
        brand="Demo Brand",
        style_no="DEMO001",
        garment="Kurta",
        colour="Red"
    )
    print(f"✓ Added style with ID: {style_id}")
    
    # Show initial state
    styles = get_styles_by_merchant("Demo Merchant")
    if styles:
        style = styles[0]
        print(f"✓ Initial stage: {STAGE_LABELS[style.stage]} (stage {style.stage})")
    
    # Progress through stages
    stages_to_demo = [1, 3, 5, 8, 10, 13]  # Fit, Bulk, FPT, Accessories, Stitching, Dispatch
    
    for stage_num in stages_to_demo:
        update_style_stage(style_id, stage_num)
        print(f"✓ Updated to: {STAGE_LABELS[stage_num]} (stage {stage_num})")
        
        # Check if style is still active
        styles = get_styles_by_merchant("Demo Merchant")
        if styles:
            style = styles[0]
            print(f"  - Active: {style.active}")
        else:
            print("  - Style is now inactive (Dispatch stage)")
            break
    
    print("\n🎉 Stage management demo completed!")
    print("\nIn Slack, users can:")
    print("1. /add-style → Create new style (starts at Pre-fit)")
    print("2. /update-stage → Progress through stages")
    print("3. /current-styles → View active styles with current stages")

if __name__ == "__main__":
    demo_stage_management() 