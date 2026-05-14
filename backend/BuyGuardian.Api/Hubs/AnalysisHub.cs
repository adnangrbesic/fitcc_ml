using Microsoft.AspNetCore.SignalR;
using System.Threading.Tasks;

namespace BuyGuardian.Api.Hubs
{
    public class AnalysisHub : Hub
    {
        // Clients can manually join groups if needed, but we can also broadcast to all
        // or broadcast based on the itemId. For simplicity and robustness, we can broadcast to all connected clients
        // and let the client filter by itemId, or use a group for the itemId.
        // We'll use groups for itemId to be more efficient.
        
        public async Task JoinGroup(string itemId)
        {
            await Groups.AddToGroupAsync(Context.ConnectionId, itemId);
        }

        public async Task LeaveGroup(string itemId)
        {
            await Groups.RemoveFromGroupAsync(Context.ConnectionId, itemId);
        }
    }
}
