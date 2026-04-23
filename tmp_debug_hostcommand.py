import sys
sys.path.insert(0, 'd:/nvda-addons/NVDA-AI-assistant')
from addon.globalPlugins.AI_assistant.ui.host_protocol import HostCommand
cmd = HostCommand(name='render_display', payload={'title': 'Test'})
text = cmd.to_json()
print(text)
print('has id', '"id":' in text)
