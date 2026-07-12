import {copyFileSync, mkdirSync} from "node:fs"
import {join} from "node:path"

const destination=join("dist","licenses","klinecharts")
mkdirSync(destination,{recursive:true})
for(const name of ["LICENSE","NOTICE"]){copyFileSync(join("node_modules","klinecharts",name),join(destination,name))}
copyFileSync("THIRD_PARTY_NOTICES.md",join("dist","THIRD_PARTY_NOTICES.md"))
