import React, { useState, useEffect, useCallback } from 'react';
import { ChevronLeft, ChevronRight, PlayCircle, ExternalLink } from 'lucide-react';

const MagicPhraseSlide = () => {
  const [step, setStep] = useState(0);

  return (
    <div 
      className="flex flex-col items-center justify-center h-full space-y-12 cursor-pointer w-full select-none relative"
      onClick={() => setStep(s => Math.min(s + 1, 2))}
    >
      <h1 className="text-7xl font-black tracking-tight flex flex-wrap justify-center items-center gap-6">
        <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#8acaff] to-[#3253DC]">
          POLICY
        </span>
        {step >= 1 && (
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-[#8acaff] to-[#3253DC] opacity-80">
            ... AS ...
          </span>
        )}
        {step >= 2 && (
          <div className="relative ml-8">
            {/* Crazy background effects */}
            <div className="absolute -inset-10 bg-gradient-to-r from-red-500 via-yellow-500 to-purple-500 opacity-30 blur-2xl rounded-full animate-pulse"></div>
            
            <span className="relative inline-block text-transparent bg-clip-text bg-gradient-to-r from-red-400 via-yellow-400 to-green-400 animate-[bounce_0.5s_infinite] scale-[1.3] transform -rotate-6 drop-shadow-[0_0_20px_rgba(255,255,255,0.5)] font-black text-8xl">
              CODE!!!
            </span>
          </div>
        )}
      </h1>
      
      <p className={`text-2xl text-slate-400 text-center max-w-2xl transition-opacity duration-1000 ${step >= 2 ? 'opacity-100' : 'opacity-0'}`}>
        Say this to an Enterprise Architect or Security Architect and watch them go <span className="font-bold text-white">bananas</span>.
      </p>
      
      {step < 2 && (
        <div className="absolute bottom-0 animate-pulse text-slate-500 text-base font-medium">
          Click anywhere to reveal...
        </div>
      )}
    </div>
  );
};

const slides = [
  {
    title: "The Governance Question We All Dread",
    content: (
      <div className="space-y-6">
        <blockquote className="text-3xl font-light italic border-l-4 border-[#8acaff] pl-6 py-2 text-slate-300">
          "Can you prevent people from doing XYZ in Databricks?"
        </blockquote>
        <p className="text-2xl text-slate-400">
          And the answer has historically been: <strong>"No, sorry. Anyone with access can do that."</strong>
        </p>
        <div className="bg-[#11151c] border border-slate-800 rounded-lg p-8 mt-8">
          <h3 className="text-xl font-semibold text-[#8acaff] mb-4">The Complexity Reality: What Natively Falls Through the Cracks</h3>
          <ul className="space-y-4 text-slate-300 list-disc list-inside text-lg">
            <li>"All clusters and jobs must have a 'CostCenter' tag"</li>
            <li>"Dashboards cannot be shared with 'All Workspace Users'"</li>
            <li>"Service Principals cannot be granted Workspace Admin privileges"</li>
            <li>"Workspace assets (Jobs, Dashboards) cannot be owned by deactivated users"</li>
          </ul>
        </div>
      </div>
    )
  },
  {
    title: "The Magic Phrase",
    content: <MagicPhraseSlide />
  },
  {
    title: "Mini KT: OPA & Rego",
    content: (
      <div className="grid grid-cols-2 gap-12">
        <div className="space-y-6">
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-8">
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-2xl font-bold text-[#8acaff] flex items-center">
                <span className="bg-[#3253DC] text-white text-sm px-2 py-1 rounded mr-3">ENGINE</span>
                OPA
              </h3>
              <img 
                src="https://www.openpolicyagent.org/img/nav/logo.png" 
                alt="OPA Logo" 
                className="h-12 brightness-0 invert opacity-80" 
              />
            </div>
            <p className="text-slate-300 text-lg font-medium mb-2">Open Policy Agent</p>
            <p className="text-slate-400 text-lg mb-4">Takes a policy in one hand, a set of facts in the other, smooshes them together and returns "yes" or "no" (or an action).</p>
            <p className="text-slate-500 text-lg italic">Think of it as a pure boolean evaluation engine.</p>
          </div>
        </div>
        
        <div className="space-y-6">
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-8">
            <div className="flex items-start justify-between mb-4">
              <h3 className="text-2xl font-bold text-[#8acaff] flex items-center">
                <span className="bg-[#3253DC] text-white text-sm px-2 py-1 rounded mr-3">LANGUAGE</span>
                Rego
              </h3>
              <div className="h-12 w-12 bg-gradient-to-br from-[#8acaff] to-[#3253DC] rounded-xl flex items-center justify-center opacity-90 shadow-lg">
                <span className="text-white font-black text-2xl tracking-tighter">Re</span>
              </div>
            </div>
            <p className="text-slate-300 text-lg font-medium mb-2">The language of policy</p>
            <p className="text-slate-400 text-lg mb-4">Declarative and simple. But what do all good languages allow? <strong className="text-white">Inheritance and Reusability.</strong></p>
            <p className="text-slate-500 text-lg italic">DRY not WET. That's Rego's superpower.</p>
          </div>
        </div>
        
        <div className="col-span-2 flex justify-center mt-4">
          <a 
            href="/policies" 
            target="_blank" 
            rel="noopener noreferrer"
            className="flex items-center px-8 py-4 text-lg bg-[#3253DC] hover:bg-[#2841b5] text-white font-medium rounded-md transition-colors"
          >
            <PlayCircle className="w-6 h-6 mr-3" />
            Show OPA Playground
            <ExternalLink className="w-5 h-5 ml-3 opacity-70" />
          </a>
        </div>
      </div>
    )
  },
  {
    title: "Mechanics: The Policy Enforcement Sentinel",
    content: (
      <div className="space-y-8">
        <p className="text-xl text-slate-300 flex items-center justify-between">
          <span>How does this mechanically work at a workspace level? Introducing the reusable asset.</span>
          <span className="text-sm px-4 py-1.5 bg-[#ff3621]/10 text-[#ff3621] border border-[#ff3621]/20 rounded-full font-medium flex items-center">
            Runs as a Databricks App
          </span>
        </p>
        
        <div className="grid grid-cols-3 gap-6">
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 relative overflow-hidden flex flex-col">
            <div className="absolute top-0 left-0 right-0 h-1 bg-blue-500"></div>
            <h3 className="text-xl font-semibold text-white mb-4 flex flex-col gap-2">
              <span className="bg-slate-800 text-slate-300 text-sm px-2 py-1 rounded w-fit">PHASE 1</span>
              Discovery
            </h3>
            <p className="text-slate-400 text-base flex-1">On a configurable scheduled cadence, a Background worker loop asynchronously loops through all assets in a workspace, applying each policy to each asset.</p>
          </div>

          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 relative overflow-hidden flex flex-col">
            <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500"></div>
            <h3 className="text-xl font-semibold text-white mb-4 flex flex-col gap-2">
              <span className="bg-slate-800 text-slate-300 text-sm px-2 py-1 rounded w-fit">PHASE 2</span>
              Enforcement
            </h3>
            <p className="text-slate-400 text-base flex-1">What action do we take on violation? Are we killing this on the spot? Are we flipping a tag or certification status?</p>
          </div>

          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 relative overflow-hidden flex flex-col">
            <div className="absolute top-0 left-0 right-0 h-1 bg-emerald-500"></div>
            <h3 className="text-xl font-semibold text-white mb-4 flex flex-col gap-2">
              <span className="bg-slate-800 text-slate-300 text-sm px-2 py-1 rounded w-fit">PHASE 3</span>
              Notification
            </h3>
            <p className="text-slate-400 text-base flex-1">We notify. Maybe that's the governance team, maybe that's policy violators directly.</p>
          </div>
        </div>
        
        <div className="flex justify-center mt-8">
           <span className="inline-block px-5 py-2.5 bg-slate-800/50 text-slate-300 rounded-full text-base font-medium border border-slate-700">
             [ Demo Time: Dashboard & Allowlist ]
           </span>
        </div>
      </div>
    )
  },
  {
    title: "The Unvarnished Truth",
    content: (
      <div className="space-y-6">
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-6 flex flex-col items-center text-center relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-red-500"></div>
            <div className="bg-red-500/20 text-red-400 p-2 w-12 h-12 text-xl rounded-full flex items-center justify-center font-bold mb-4">1</div>
            <h3 className="text-xl font-semibold text-red-200 mb-3 leading-tight">Not a replacement for Unity Catalog</h3>
            <p className="text-slate-400 text-base">If you can manage a permission natively in Unity Catalog, prefer that. This fills the gaps.</p>
          </div>
          
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-6 flex flex-col items-center text-center relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-amber-500"></div>
            <div className="bg-amber-500/20 text-amber-400 p-2 w-12 h-12 text-xl rounded-full flex items-center justify-center font-bold mb-4">2</div>
            <h3 className="text-xl font-semibold text-amber-200 mb-3 leading-tight">Reactive, not Proactive</h3>
            <p className="text-slate-400 text-base">Don't count on this for mission-critical security. The platform is designed to let users build; we catch the drift post-creation.</p>
          </div>

          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-6 flex flex-col items-center text-center relative overflow-hidden">
            <div className="absolute top-0 left-0 right-0 h-1 bg-blue-500"></div>
            <div className="bg-blue-500/20 text-blue-400 p-2 w-12 h-12 text-xl rounded-full flex items-center justify-center font-bold mb-4">3</div>
            <h3 className="text-xl font-semibold text-blue-200 mb-3 leading-tight">Beware the Blast Radius</h3>
            <p className="text-slate-400 text-base">The Service Principal this runs as needs wide-ranging permissions. Consider the Principle of Least Privilege (PLP) and blast radius.</p>
          </div>
        </div>
      </div>
    )
  },
  {
    title: "Questions & Dessert Menu",
    content: (
      <div className="space-y-6">
        <p className="text-xl text-slate-300 mb-4">
          Want to go deeper? Pick your poison:
        </p>

        <div className="grid grid-cols-3 gap-6">
          
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">Throw a Scenario!</h3>
            <p className="text-slate-400 text-base">"Can it do XYZ if A=B?"</p>
          </div>
          
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">Code Tour</h3>
            <p className="text-slate-400 text-base">Show me the discovery and enforcement handlers.</p>
          </div>
          
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">MCP Integration</h3>
            <p className="text-slate-400 text-base">Yes, there's an MCP tool included! Add it to Databricks Genie.</p>
          </div>
          
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">Performance at Scale</h3>
            <p className="text-slate-400 text-base">How does this handle thousands of assets?</p>
          </div>
          
          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">Enforce ODCS/ODPS</h3>
            <p className="text-slate-400 text-base">Using this as the mechanism for enforcing ODCS/ODPS.</p>
          </div>          

          <div className="bg-[#11151c] border border-slate-800 rounded-lg p-6 hover:bg-[#1a212b] transition-colors cursor-pointer group">
            <h3 className="text-xl font-semibold text-[#8acaff] group-hover:text-white transition-colors mb-2">Splunk Integration</h3>
            <p className="text-slate-400 text-base">Forwarding policy violations and events to Splunk.</p>
          </div>
        </div>

        <div className="mt-5 pt-5 border-t border-slate-800 flex justify-center items-center text-slate-400">
          <ExternalLink className="w-5 h-5 mr-3 opacity-70" />
          <span className="text-lg">Get the code: </span>
          <a 
            href="https://github.com/databricks-field-eng/policy-enforcement-sentinel" 
            target="_blank" 
            rel="noopener noreferrer"
            className="ml-2 text-[#8acaff] hover:text-[#b3d9ff] font-medium transition-colors text-lg"
          >
            github.com/databricks-field-eng/policy-enforcement-sentinel
          </a>
        </div>
      </div>
    )
  }
];

export default function Presentation() {
  const [currentSlide, setCurrentSlide] = useState(0);

  const nextSlide = useCallback(() => {
    setCurrentSlide((prev) => Math.min(prev + 1, slides.length - 1));
  }, []);

  const prevSlide = useCallback(() => {
    setCurrentSlide((prev) => Math.max(prev - 1, 0));
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'Space') {
        nextSlide();
      } else if (e.key === 'ArrowLeft') {
        prevSlide();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [nextSlide, prevSlide]);

  const slide = slides[currentSlide];

  return (
    <div className="flex flex-col h-full bg-[#0b0f15]">
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-6xl aspect-video bg-[#0d1219] border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col relative">
          
          {/* Progress bar */}
          <div className="absolute top-0 left-0 right-0 h-1 bg-slate-800">
            <div 
              className="h-full bg-[#3253DC] transition-all duration-300"
              style={{ width: `${((currentSlide + 1) / slides.length) * 100}%` }}
            />
          </div>

          <div className="p-10 flex-1 flex flex-col overflow-hidden">
            <h2 className="text-4xl font-bold text-white mb-6 pb-4 border-b border-slate-800/50 shrink-0">
              {slide.title}
            </h2>
            <div className="flex-1 overflow-y-auto pr-4">
              {slide.content}
            </div>
          </div>
          
          {/* Slide Footer */}
          <div className="px-8 py-4 border-t border-slate-800 flex justify-between items-center text-base text-slate-500">
            <span>Policy Enforcement Sentinel</span>
            <span>{currentSlide + 1} / {slides.length}</span>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="h-20 flex items-center justify-center space-x-6 shrink-0">
        <button
          onClick={prevSlide}
          disabled={currentSlide === 0}
          className="p-3 rounded-full hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent transition-colors text-slate-300"
        >
          <ChevronLeft className="w-8 h-8" />
        </button>
        
        <div className="flex space-x-2">
          {slides.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentSlide(idx)}
              className={`w-3 h-3 rounded-full transition-colors ${
                currentSlide === idx ? 'bg-[#8acaff]' : 'bg-slate-700 hover:bg-slate-500'
              }`}
            />
          ))}
        </div>

        <button
          onClick={nextSlide}
          disabled={currentSlide === slides.length - 1}
          className="p-3 rounded-full hover:bg-slate-800 disabled:opacity-30 disabled:hover:bg-transparent transition-colors text-slate-300"
        >
          <ChevronRight className="w-8 h-8" />
        </button>
      </div>
    </div>
  );
}