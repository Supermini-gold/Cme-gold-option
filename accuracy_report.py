import matplotlib.pyplot as plt
import io

def generate_accuracy_dashboard(total_analyzed, total_accurate):
    if total_analyzed == 0:
        win_rate = 0
    else:
        win_rate = (total_accurate / total_analyzed) * 100

    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(8, 4))
    
    # Text data
    ax.text(0.5, 0.8, 'AI Accuracy Dashboard', fontsize=24, ha='center', color='#FFD700', weight='bold')
    
    # Determine color based on win rate
    wr_color = '#00ffcc' if win_rate >= 50 else '#ff4444'
    ax.text(0.5, 0.5, f'Win Rate: {win_rate:.1f}%', fontsize=36, ha='center', color=wr_color, weight='bold')
    
    ax.text(0.5, 0.2, f'Total Analyzed: {total_analyzed} | Accurate: {total_accurate} | Missed: {total_analyzed - total_accurate}', fontsize=16, ha='center', color='#cccccc')
    
    ax.axis('off')
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor='#121212')
    buf.seek(0)
    plt.close()
    return buf.getvalue()

if __name__ == "__main__":
    b = generate_accuracy_dashboard(10, 7)
    with open("test_dashboard.png", "wb") as f:
        f.write(b)
