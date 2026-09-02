import type { NextFunction, Request, Response } from "express";
import { randomUUID } from "node:crypto";
const UUID_RE=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export class CorrelationIdMiddleware{
 use=(req:Request,res:Response,next:NextFunction)=>{const incoming=req.header("x-correlation-id");const id=incoming && UUID_RE.test(incoming)?incoming:randomUUID();res.setHeader("x-correlation-id",id);next();};
}
