local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local player = Players.LocalPlayer

local Cat, b, c = "Cat", false, {}

while true do
	local ok, result = pcall(function()
		return MarketplaceService:PromptBulkPurchase(player, Cat, b, c)
	end)

	if ok and result == nil then -- [true nil] with Delta
		player:Kick("Delta executor")
		break
	end

	task.wait(0.1)
end