import os
import aiohttp
from src.utils import make_logger

log = make_logger('integrations')

async def file_linear_ticket(title: str, description: str, priority: int = 2):
    """
    Files a ticket in Linear.
    priority: 1=Urgent, 2=High, 3=Normal, 4=Low
    """
    token = os.environ.get('LINEAR_API_KEY')
    team_id = os.environ.get('LINEAR_TEAM_ID')
    
    if not token or not team_id:
        log.warning("Linear integration not configured (LINEAR_API_KEY, LINEAR_TEAM_ID missing)")
        return None
        
    url = "https://api.linear.app/graphql"
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    
    mutation = """
    mutation IssueCreate($title: String!, $description: String, $teamId: String!, $priority: Int) {
      issueCreate(input: {
        title: $title,
        description: $description,
        teamId: $teamId,
        priority: $priority
      }) {
        success
        issue {
          id
          url
        }
      }
    }
    """
    
    variables = {
        "title": f"[Casefile] {title}",
        "description": description,
        "teamId": team_id,
        "priority": priority
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"query": mutation, "variables": variables}, headers=headers) as resp:
                data = await resp.json()
                if data.get('errors'):
                    log.error(f"Linear GraphQL error: {data['errors']}")
                    return None
                
                issue = data.get('data', {}).get('issueCreate', {}).get('issue')
                if issue:
                    log.info(f"Successfully filed Linear ticket: {issue['url']}")
                    return issue['url']
    except Exception as e:
        log.error(f"Failed to file Linear ticket: {e}")
        
    return None
