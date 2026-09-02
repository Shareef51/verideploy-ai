import { Global, Module } from "@nestjs/common";
import { PrivateAiClient } from "./private-ai.client";
@Global() @Module({providers:[PrivateAiClient],exports:[PrivateAiClient]}) export class BoundaryModule{}
