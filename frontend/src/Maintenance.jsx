import { useState, useEffect } from "react";
import axios from "axios";
import { FileUp, Upload, Loader2 } from 'lucide-react';
import Navbar from "./Navbar";
import Info from "./Info";
import cat from '/cat.gif'
const Maintenance = () => {

  return (
    <>
      <Navbar />
      <div className="flex flex-col items-center">
        <div className="mt-20 items-center flex flex-col p-3">
          <h1 className="text-3xl text-center font-libre tracking-wider">UNDERGOING FIXES. CONTACT ARVIND IF NEEDED.</h1>
            <img src={cat} className="m-4 "></img>
        </div>
      </div>
    </>
  );
};

export default Maintenance;