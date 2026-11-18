-- /csexport : record the vendor sell price of every item in Items.lua.
-- WoW writes SavedVariables to disk only on /reload or logout.

local function itemInfo(id)
  local name, _, _, _, _, _, _, _, _, _, sellPrice = GetItemInfo(id)
  return name, sellPrice
end

local function requestLoad(id)
  if C_Item and C_Item.RequestLoadItemDataByID then
    C_Item.RequestLoadItemDataByID(id)
  end
end

local function export(attempt)
  local db = { sell = {}, names = {}, exported = date("%Y-%m-%d %H:%M") }
  local missing = 0
  for _, id in ipairs(CheapestSkillupExport_Items) do
    local name, sell = itemInfo(id)
    if name then
      db.sell[id] = sell or 0
      db.names[id] = name
    else
      missing = missing + 1
      requestLoad(id)
    end
  end
  CheapestSkillupExportDB = db

  if missing > 0 and attempt < 5 then
    print(("|cffe0a440Cheapest Skill-up:|r waiting for %d item(s) from the server..."):format(missing))
    C_Timer.After(2, function() export(attempt + 1) end)
    return
  end
  local found = #CheapestSkillupExport_Items - missing
  print(("|cffe0a440Cheapest Skill-up:|r exported %d vendor price(s)%s. Type |cffffffff/reload|r to save the file."):format(
    found, missing > 0 and (", " .. missing .. " unknown to this client") or ""))
end

SLASH_CSEXPORT1 = "/csexport"
SlashCmdList.CSEXPORT = function() export(1) end
